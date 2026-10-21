#!/usr/bin/env python3
"""Director-controlled, project-local orchestration backlog.

This is a manual bookkeeping CLI, not an agent launcher or scheduler. Mutations
are serialized with an exclusive lock and written with atomic replacement.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import PureWindowsPath
from pathlib import Path
from typing import Any, Optional

SCHEMA = 1
DB_REL = Path('.codex') / 'ORCHESTRATOR.json'
STATE_REL = Path('.codex') / 'PROJECT_STATE.md'
BOOKKEEPING = {DB_REL.as_posix(), STATE_REL.as_posix(), (Path('.codex') / 'ORCHESTRATOR.lock').as_posix()}
SELECTOR_REL = Path('.codex') / 'ORCHESTRATOR_STORAGE.json'
BOOTSTRAP_REL = Path('.codex') / 'ORCHESTRATOR_STORAGE.lock'
ACTIVE_DATA_DIR: Optional[Path] = None
STATES = {'planned', 'assigned', 'in_progress', 'ready_for_review', 'interrupted', 'integrated', 'completed', 'blocked'}
ROLE_MODELS = {'sol_reviewer': 'gpt-6.1-sol', 'sol_senior': 'gpt-6.1-sol', 'astra_consultant': 'gpt-6-astra'}
STAT_KEYS = ('seq event wall_time_ms task_ref actor_ref participant_ref previous_participant_ref attempt contract_revision review_round from_state to_state requested_role canonical_model canonical_effort request_source observed_model observed_effort observed_service_tier observed_tokens observed_cost observed_ui_confirmation_count observed_source verification_result verification_check_count verification_unrun_count verification_source elapsed_ms elapsed_source clock_anomaly active_work_ms human_wait_ms').split()
STAT_EVENTS = {'created':'created','replanned':'replanned','acceptance_plan_recorded':'acceptance_plan_recorded','assigned':'assigned','in_progress':'in_progress','interrupted':'interrupted','ready_for_review':'ready_for_review','recovered':'recovered','escalated':'escalated','review_pass':'review_pass','review_fail':'review_fail','review_inconclusive':'review_inconclusive','integrated':'integrated','completed':'completed','consultation_recorded':'consultation_recorded'}
ROLE_DEFAULTS = {'luna_worker':('gpt-6-luna','medium'),'luna_reviewer':('gpt-6-luna','high'),'luna_state_editor':('gpt-6-luna','low'),'sol_senior':('gpt-6.1-sol','high'),'sol_reviewer':('gpt-6.1-sol','high'),'astra_consultant':('gpt-6-astra','high')}
PLAN_CONTEXT_ITEMS = {'contract', 'diff', 'relevant-code', 'verification-results'}
TRANSITIONS = {
    'planned': {'assigned', 'blocked'}, 'assigned': {'in_progress', 'interrupted', 'planned'},
    'in_progress': {'ready_for_review', 'interrupted', 'blocked', 'assigned'},
    'ready_for_review': {'in_progress', 'integrated', 'blocked', 'assigned'},
    'interrupted': {'blocked'}, 'blocked': {'planned'}, 'integrated': {'completed', 'in_progress'},
    'completed': set(),
}
EVENT_STATE_PAIRS = {
    'created': {(None,'planned')},
    'replanned': {('planned','planned'),('blocked','planned')},
    'acceptance_plan_recorded': {('planned','planned')},
    'assigned': {('planned','assigned')},
    'in_progress': {('assigned','in_progress'),('ready_for_review','in_progress'),('integrated','in_progress')},
    'interrupted': {('assigned','interrupted'),('in_progress','interrupted')},
    'ready_for_review': {('in_progress','ready_for_review')},
    'recovered': {('interrupted','assigned')},
    'escalated': {('in_progress','assigned'),('ready_for_review','assigned')},
    'review_pass': {('ready_for_review','ready_for_review')},
    'review_fail': {('ready_for_review','in_progress'),('ready_for_review','blocked')},
    'review_inconclusive': {('ready_for_review','blocked')},
    'integrated': {('ready_for_review','integrated')},
    'completed': {('integrated','completed')},
    'consultation_recorded': {(state,state) for state in STATES},
}

class OrchestrationError(Exception):
    pass

def git(root: Path, *args: str) -> str:
    # In particular, status must not refresh the user's index/stat cache.
    try:
        p = subprocess.run(['git', '--no-optional-locks', *args], cwd=root, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        raise OrchestrationError(f"cannot verify Git state: {exc}") from exc
    stderr = p.stderr.decode('utf-8', errors='surrogateescape').strip()
    if p.returncode:
        raise OrchestrationError(f"git {' '.join(args)} failed: {stderr}")
    if stderr:
        # Git can return zero while warning that an untracked directory could
        # not be opened. Such an inventory is not a verified snapshot.
        raise OrchestrationError(f"git {' '.join(args)} could not be verified: {stderr}")
    # Text-mode universal newline decoding would rewrite literal CR/LF in
    # NUL-delimited POSIX filenames before the containment/read checks.
    return p.stdout.decode('utf-8', errors='surrogateescape')

def project_root(path: Path) -> Path:
    try:
        return Path(git(path, 'rev-parse', '--show-toplevel').strip()).resolve()
    except (OSError, OrchestrationError):
        raise OrchestrationError(f'not inside a git project: {path}')

def _is_reparse_or_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & reparse_flag) or bool(getattr(path, 'is_junction', lambda: False)())

def git_path_parts(rel: str, platform: str = os.name) -> list[str]:
    """Split a Git path using Git's slash separator without rewriting names."""
    if not rel or rel.startswith('/') or '\x00' in rel:
        raise OrchestrationError(f'unsafe Git path: {rel!r}')
    parts = rel.split('/')
    if any(part in {'', '.', '..'} for part in parts):
        raise OrchestrationError(f'unsafe Git path: {rel!r}')
    # Windows cannot represent a literal backslash in a filename; Git paths
    # from that worktree must never reinterpret one as another path component.
    if platform == 'nt' and any('\\' in part for part in parts):
        raise OrchestrationError(f'unsafe backslash in Windows Git path: {rel!r}')
    return parts

def git_worktree_path(root: Path, rel: str) -> Path:
    """Map a Git slash path into the project, preserving POSIX backslashes."""
    parts = git_path_parts(rel)
    base = root.resolve()
    candidate = root.joinpath(*parts)
    parent = candidate.parent.resolve(strict=False)
    try:
        parent.relative_to(base)
    except ValueError:
        raise OrchestrationError(f'Git path escapes project through a parent link: {rel!r}')
    return candidate

def codex_dir(root: Path, create: bool = False) -> Path:
    """Return the selected, contained ledger directory, validating every component."""
    base=root.resolve()
    directory=ACTIVE_DATA_DIR or (base / '.codex')
    if not directory.is_absolute(): directory=base / directory
    directory=Path(os.path.abspath(directory))
    try:
        rel=directory.relative_to(base)
        current=base
        for part in rel.parts:
            current=current / part
            if _is_reparse_or_link(current): raise OrchestrationError(f'refusing storage symlink/junction/reparse point: {current}')
        directory.resolve(strict=False).relative_to(base)
    except (OSError, ValueError):
        raise OrchestrationError(f'storage resolves outside project: {directory}')
    if directory.exists() and not directory.is_dir(): raise OrchestrationError(f'storage is not a directory: {directory}')
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory

def worktree_value(root: Path, rel: str, skipped: bool = False) -> str:
    """Read actual bytes/type/mode; never turn an inspection error into data.

    Materialized assume-unchanged and skip-worktree files are read normally.
    Absent skip-worktree files (including sparse checkout omissions) cannot be
    verified here and are refused rather than substituted with index content.
    """
    try:
        path = git_worktree_path(root, rel)
        parent = path.parent.resolve()
        try:
            before = path.lstat()
        except FileNotFoundError:
            if skipped:
                raise OrchestrationError(f'cannot verify absent skip-worktree/sparse path: {rel}')
            return '<deleted>'
        reparse_flag = getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
        if stat.S_ISLNK(before.st_mode):
            value = 'symlink:' + os.readlink(path)
        elif bool(getattr(before, 'st_file_attributes', 0) & reparse_flag):
            raise OrchestrationError(f'cannot verify worktree reparse point: {rel}')
        elif stat.S_ISREG(before.st_mode):
            value = 'file:' + hashlib.sha256(path.read_bytes()).hexdigest()
            if os.name == 'posix':
                value += ':executable' if before.st_mode & 0o111 else ':non-executable'
        else:
            raise OrchestrationError(f'unsupported worktree file type; cannot verify: {rel}')
        after = path.lstat()
        # Detect replacement, type/mode changes and edits during the read.
        identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size,
                                 info.st_mtime_ns, info.st_ctime_ns)
        git_worktree_path(root, rel)
        if identity(before) != identity(after) or path.parent.resolve() != parent:
            raise OrchestrationError(f'worktree changed during snapshot: {rel}')
        return value
    except (OSError, ValueError) as exc:
        raise OrchestrationError(f'cannot verify worktree path {rel!r}: {exc}') from exc


def snapshot(root: Path) -> dict[str, Any]:
    """Bind HEAD, semantic index and actual worktree, regardless of Git flags."""
    head = git(root, 'rev-parse', 'HEAD').strip()
    raw = git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')
    # Hash semantic index entries (mode, object id, conflict stage), not the
    # raw .git/index file whose stat cache can change during git status.
    index_output = git(root, 'ls-files', '--stage', '-z')
    flags_output = git(root, 'ls-files', '-v', '-z')
    flagged_paths = set()
    skipped_paths = set()
    for entry in flags_output.split('\0'):
        if not entry: continue
        if len(entry) < 3 or entry[1] != ' ':
            raise OrchestrationError('unexpected output from git ls-files -v')
        tag, rel = entry[0], entry[2:]
        if tag == 'S' or tag == 's': skipped_paths.add(rel)
        if tag.islower() or tag == 'S': flagged_paths.add(rel)
    bookkeeping_paths={git_path_identity(rel) for rel in bookkeeping(root)}
    index_entries=[]
    for entry in index_output.split('\0'):
        if not entry: continue
        try: metadata, rel = entry.split('\t', 1)
        except ValueError: raise OrchestrationError('unexpected output from git ls-files --stage')
        if git_path_identity(rel) in bookkeeping_paths: continue
        git_worktree_path(root, rel)
        if metadata.split()[0] == '160000':
            raise OrchestrationError(f'gitlink/submodule snapshot is unsupported; refusing an incomplete snapshot: {rel}')
        if metadata.split()[0] not in {'100644', '100755', '120000'}:
            raise OrchestrationError(f'unsupported index mode/sparse directory; cannot verify: {rel}')
        index_entries.append((rel,metadata))
    index_digest = hashlib.sha256(json.dumps(sorted(index_entries),separators=(',',':')).encode()).hexdigest()
    head_output=git(root,'ls-tree','-r','--full-tree','-z','HEAD')
    head_entries=[]
    for entry in head_output.split('\0'):
        if not entry: continue
        try: metadata,rel=entry.split('\t',1)
        except ValueError: raise OrchestrationError('unexpected output from git ls-tree')
        if git_path_identity(rel) in bookkeeping_paths: continue
        git_worktree_path(root, rel)
        if metadata.split()[0] == '160000':
            raise OrchestrationError(f'gitlink/submodule snapshot is unsupported; refusing an incomplete snapshot: {rel}')
        head_entries.append((rel,metadata))
    head_tree_digest=hashlib.sha256(json.dumps(sorted(head_entries),separators=(',',':')).encode()).hexdigest()
    entries = raw.split('\0')
    changed: dict[str, str] = {}
    # HEAD paths also matter after staged removal: an ignored leftover at a
    # formerly tracked path is still actual worktree content.
    worktree = {rel: worktree_value(root, rel, rel in skipped_paths)
                for rel in sorted({rel for rel, _ in index_entries + head_entries})}
    paths: list[str] = []
    i = 0
    while i < len(entries):
        item = entries[i]
        i += 1
        if not item: continue
        code, name = item[:2], item[3:]
        names = [name]
        if 'R' in code or 'C' in code:
            if i < len(entries) and entries[i]: names.append(entries[i]); i += 1
        for rel in names:
            if git_path_identity(rel) in bookkeeping_paths: continue
            paths.append(rel)
            if rel not in worktree:
                worktree[rel] = worktree_value(root, rel, rel in skipped_paths)
            changed[rel] = code
    # Include flagged paths in diagnostics even when Git status hides them.
    paths.extend(rel for rel in flagged_paths if rel in worktree)
    # A later read can race an edit to an earlier flagged file that status
    # never reports. Require a second actual-content pass to agree as well.
    for rel, value in worktree.items():
        if worktree_value(root, rel, rel in skipped_paths) != value:
            raise OrchestrationError(f'worktree changed during snapshot: {rel}')
    if (head != git(root, 'rev-parse', 'HEAD').strip()
            or index_output != git(root, 'ls-files', '--stage', '-z')
            or flags_output != git(root, 'ls-files', '-v', '-z')
            or raw != git(root, 'status', '--porcelain=v1', '-z', '--untracked-files=all')):
        raise OrchestrationError('Git state changed during snapshot; retry after writers stop')
    dirty_digest = hashlib.sha256(json.dumps({'changed': changed, 'worktree': worktree}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    exact_fingerprint=hashlib.sha256(f'{head}:{index_digest}:{dirty_digest}'.encode()).hexdigest()
    state_fingerprint=hashlib.sha256(f'{head_tree_digest}:{index_digest}:{dirty_digest}'.encode()).hexdigest()
    return {'head': head, 'index_digest': index_digest, 'head_tree_digest':head_tree_digest,'dirty_digest': dirty_digest, 'paths': sorted(set(paths)), 'fingerprint': exact_fingerprint,'state_fingerprint':state_fingerprint}

def bookkeeping(root: Path) -> set[str]:
    base=root.resolve()
    selected=codex_dir(root)
    rel=selected.relative_to(base).as_posix()
    return {STATE_REL.as_posix(), BOOTSTRAP_REL.as_posix(), (Path('.codex')/'ORCHESTRATOR.lock').as_posix(),
            (Path(rel)/'ORCHESTRATOR.json').as_posix(), (Path(rel)/'ORCHESTRATOR.lock').as_posix(),
            (Path(rel)/'ORCHESTRATOR.tmp').as_posix()}

def git_path_identity(rel: str) -> str:
    """Return a comparison key matching the host worktree's path identity."""
    return os.path.normcase(rel) if os.name == 'nt' else rel

def regular_file_identity(path: Path) -> Optional[tuple[int, int]]:
    """Return a regular, non-link file identity, or None for anything unsafe."""
    try:
        info=path.lstat()
    except FileNotFoundError:
        return None
    reparse_flag=getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)
    if (not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or not info.st_ino
            or bool(getattr(info, 'st_file_attributes', 0) & reparse_flag)):
        return None
    return info.st_dev, info.st_ino

def safe_contained_path(root: Path, raw: str) -> Path:
    base=root.resolve()
    if not isinstance(raw,str) or not raw.strip(): raise OrchestrationError('data directory must be a nonempty path')
    lexical=Path(raw)
    if '..' in lexical.parts: raise OrchestrationError('data directory cannot contain a parent traversal')
    if os.name=='nt' and not lexical.is_absolute() and PureWindowsPath(raw).drive:
        raise OrchestrationError('drive-relative data directories are unsupported')
    candidate=Path(raw)
    candidate=candidate if candidate.is_absolute() else base/candidate
    candidate=Path(os.path.abspath(candidate))
    try:
        rel=candidate.relative_to(base); current=base
        if rel.parts and (rel.parts[0]=='.git' or rel.parts[0].casefold()=='.git'):
            raise OrchestrationError('data directory cannot be inside Git metadata')
        if rel.parts and rel.parts[0].casefold()=='.codex' and os.path.normcase(str(candidate))!=os.path.normcase(str(base/'.codex')):
            raise OrchestrationError('data directory cannot be inside protected .codex configuration')
        for part in rel.parts:
            current=current/part
            if _is_reparse_or_link(current): raise OrchestrationError(f'refusing storage symlink/junction/reparse point: {current}')
        candidate.resolve(strict=False).relative_to(base)
    except ValueError: raise OrchestrationError(f'data directory escapes project: {candidate}')
    return candidate

def selected_dir(root: Path, requested: Optional[str]) -> Path:
    global ACTIVE_DATA_DIR
    config=root/'.codex'
    if _is_reparse_or_link(config): raise OrchestrationError(f'refusing unsafe .codex config symlink/junction/reparse point: {config}')
    if config.exists() and not config.is_dir(): raise OrchestrationError(f'.codex config is not a directory: {config}')
    selector=config/SELECTOR_REL.name
    if _is_reparse_or_link(selector): raise OrchestrationError(f'refusing unsafe storage selector: {selector}')
    if selector.exists():
        try:
            data=json.loads(selector.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or set(data)!={'schema','data_dir'} or data.get('schema')!=1 or not isinstance(data.get('data_dir'),str): raise ValueError('unsupported selector shape')
            bound=safe_contained_path(root,data['data_dir'])
        except (OSError,ValueError,KeyError,TypeError) as exc: raise OrchestrationError(f'invalid storage selector: {exc}')
        if requested is not None and safe_contained_path(root,requested)!=bound: raise OrchestrationError('requested data directory differs from immutable project binding')
        if (root/DB_REL).exists(): raise OrchestrationError('legacy and bound ledgers coexist; refusing ambiguity')
        ACTIVE_DATA_DIR=bound
    else:
        if requested is not None: raise OrchestrationError('data directory is not bound; run bind-storage explicitly first')
        ACTIVE_DATA_DIR=root/'.codex'
    if ACTIVE_DATA_DIR!=root/'.codex' and (root/DB_REL).exists(): raise OrchestrationError('legacy and selected ledgers coexist; refusing ambiguity')
    return ACTIVE_DATA_DIR

def verify_selection(root: Path) -> None:
    if ACTIVE_DATA_DIR is None:
        selected_dir(root,None)
    config=root/'.codex'
    if _is_reparse_or_link(config): raise OrchestrationError(f'refusing unsafe .codex config symlink/junction/reparse point: {config}')
    if config.exists() and not config.is_dir(): raise OrchestrationError(f'.codex config is not a directory: {config}')
    selector=config/SELECTOR_REL.name
    if _is_reparse_or_link(selector): raise OrchestrationError(f'refusing unsafe storage selector: {selector}')
    if selector.exists():
        try:
            data=json.loads(selector.read_text(encoding='utf-8'))
            if not isinstance(data,dict) or set(data)!={'schema','data_dir'} or data.get('schema')!=1 or not isinstance(data.get('data_dir'),str): raise ValueError('unsupported selector shape')
            bound=safe_contained_path(root,data['data_dir'])
        except (OSError,ValueError,KeyError,TypeError) as exc: raise OrchestrationError(f'invalid storage selector: {exc}')
        if ACTIVE_DATA_DIR!=bound or (root/DB_REL).exists(): raise OrchestrationError('storage binding changed or is ambiguous')
    elif ACTIVE_DATA_DIR!=root/'.codex': raise OrchestrationError('storage selector disappeared; refusing fallback')

def empty_db(max_workers: int = 3, review_round_limit: int = 2, consultation_limit: int = 1, escalation_limit: int = 1) -> dict[str, Any]:
    return {'schema': SCHEMA, 'config': {'max_workers': max_workers, 'review_round_limit': review_round_limit, 'consultation_limit': consultation_limit, 'escalation_limit': escalation_limit}, 'tasks': {}, 'history': [], 'statistics': {'schema':1,'coverage':'new_ledger','events':[]}}

@contextlib.contextmanager
def exclusive_lock(lock: Path):
    if _is_reparse_or_link(lock): raise OrchestrationError(f'refusing unsafe lock symlink/reparse point: {lock}')
    try: fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError: raise OrchestrationError(f'backlog lock exists ({lock}); inspect the owner and remove only after confirming it is stale')
    owned_identity=None
    try:
        created=os.fstat(fd)
        if not created.st_ino:
            raise OrchestrationError('cannot establish temporary file identity')
        owned_identity=(created.st_dev,created.st_ino)
        payload=f'{os.getpid()} {time.time()}\n'.encode()
        offset=0
        while offset<len(payload):
            written=os.write(fd,payload[offset:])
            if written<=0: raise OSError('lock write made no progress')
            offset+=written
        os.fsync(fd)
        os.close(fd); fd=None
        yield
    finally:
        if fd is not None:
            try: os.close(fd)
            except OSError: pass
        if owned_identity is not None:
            try: current=lock.lstat()
            except FileNotFoundError: current=None
            except OSError as exc: raise OrchestrationError(f'cannot verify lock cleanup ownership ({lock}): {exc}') from exc
            if current is not None and (current.st_dev,current.st_ino)==owned_identity:
                if _is_reparse_or_link(lock): raise OrchestrationError(f'refusing replaced lock symlink/reparse point during cleanup: {lock}')
                try: lock.unlink()
                except OSError as exc: raise OrchestrationError(f'cannot remove owned lock ({lock}): {exc}') from exc

@contextlib.contextmanager
def locked(root: Path):
    verify_selection(root)
    d = codex_dir(root, create=True)
    lock = d / 'ORCHESTRATOR.lock'
    with exclusive_lock(lock):
        verify_selection(root)
        yield

def load(root: Path, create: bool = False) -> dict[str, Any]:
    path = codex_dir(root) / DB_REL.name
    if _is_reparse_or_link(path): raise OrchestrationError(f'refusing unsafe backlog file symlink/reparse point: {path}')
    if not path.exists():
        if create: return empty_db()
        raise OrchestrationError(f'backlog missing; run init first ({path})')
    try: db = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e: raise OrchestrationError(f'cannot read backlog: {e}')
    if not isinstance(db,dict) or db.get('schema') != SCHEMA: raise OrchestrationError('unsupported backlog object or schema')
    if 'statistics' in db: validate_statistics(db['statistics'])
    return db

def save(root: Path, db: dict[str, Any]) -> None:
    path = codex_dir(root, create=True) / DB_REL.name
    if _is_reparse_or_link(path): raise OrchestrationError(f'refusing unsafe backlog file symlink/reparse point: {path}')
    temp=path.parent/'ORCHESTRATOR.tmp'
    if _is_reparse_or_link(temp): raise OrchestrationError(f'refusing unsafe temporary file: {temp}')
    try: fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError: raise OrchestrationError(f'refusing stale/colliding temporary file: {temp}')
    owned_identity=None
    try:
        created=os.fstat(fd)
        owned_identity=(created.st_dev,created.st_ino)
        stream=os.fdopen(fd, 'w', encoding='utf-8', newline='\n')
        fd=None
        with stream as f:
            json.dump(db, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        verify_selection(root)
        current_dir=codex_dir(root)
        if (git_path_identity(str(current_dir.resolve()))!=git_path_identity(str(path.parent.resolve()))
                or _is_reparse_or_link(path)
                or regular_file_identity(temp)!=owned_identity):
            raise OrchestrationError('storage path changed before atomic publication')
        os.replace(temp, path)
    finally:
        if fd is not None:
            os.close(fd)
        if owned_identity is not None:
            current_identity=regular_file_identity(temp)
            if current_identity==owned_identity:
                temp.unlink()

def _ref(value: Optional[str], domain: str) -> Optional[str]:
    return hashlib.sha256(domain.encode()+b'\0'+value.encode('utf-8')).hexdigest() if value is not None else None

def validate_statistics(value: Any) -> dict[str, Any]:
    if not isinstance(value,dict) or set(value)!={'schema','coverage','events'} or type(value.get('schema')) is not int or value.get('schema')!=1 or not isinstance(value.get('coverage'),str) or value.get('coverage') not in {'new_ledger','legacy_partial'} or not isinstance(value.get('events'),list):
        raise OrchestrationError('invalid or unsupported statistics object')
    last_by_task={}
    for i,e in enumerate(value['events'],1):
        if not isinstance(e,dict) or set(e)!=set(STAT_KEYS) or type(e.get('seq')) is not int or e.get('seq')!=i or not isinstance(e.get('event'),str) or e.get('event') not in set(STAT_EVENTS.values()): raise OrchestrationError('invalid statistics event schema or sequence')
        if any(not isinstance(e.get(k),str) or not re.fullmatch(r'[0-9a-f]{64}',e[k]) for k in ('task_ref','actor_ref')): raise OrchestrationError('invalid statistics reference')
        for k in ('participant_ref','previous_participant_ref'):
            if e.get(k) is not None and (not isinstance(e[k],str) or not re.fullmatch(r'[0-9a-f]{64}',e[k])): raise OrchestrationError('invalid participant reference')
        for k in ('wall_time_ms','attempt','contract_revision','review_round','verification_check_count','verification_unrun_count','elapsed_ms'):
            x=e.get(k)
            if x is not None and (type(x) is not int or x<0 or x>2**63-1): raise OrchestrationError('invalid statistics numeric field')
        if (e.get('from_state') is not None and (not isinstance(e['from_state'],str) or e['from_state'] not in STATES)) or (e.get('to_state') is not None and (not isinstance(e['to_state'],str) or e['to_state'] not in STATES)): raise OrchestrationError('invalid statistics state')
        pair=(e['from_state'],e['to_state'])
        if pair not in EVENT_STATE_PAIRS[e['event']]: raise OrchestrationError('event is not allowed for its state pair')
        prior=last_by_task.get(e['task_ref'])
        if e['event']=='created' and prior is not None: raise OrchestrationError('task creation must be its first event')
        if prior is not None and e['from_state']!=prior['to_state']: raise OrchestrationError('event prior state does not follow the preceding task event')
        for k,allowed in (('requested_role',set(ROLE_DEFAULTS)),('canonical_model',{x[0] for x in ROLE_DEFAULTS.values()}),('canonical_effort',{'low','medium','high'}),('request_source',{'manual_role_declaration'}),('verification_result',{'pass','fail','inconclusive'}),('verification_source',{'manual_check_declaration'}),('elapsed_source',{'system_wall_clock_utc'}),('clock_anomaly',{'backward_clock','invalid_clock','missing_stage_timestamp'})):
            if e.get(k) is not None and (not isinstance(e[k],str) or e[k] not in allowed): raise OrchestrationError('invalid statistics enum field')
        if (e['requested_role'] is None) != (e['canonical_model'] is None) or (e['requested_role'] is None) != (e['canonical_effort'] is None) or (e['requested_role'] is None) != (e['request_source'] is None): raise OrchestrationError('inconsistent role declaration fields')
        anomaly=e['clock_anomaly']
        if e['wall_time_ms'] is None:
            if e['elapsed_ms'] is not None or anomaly!='invalid_clock': raise OrchestrationError('invalid clock fields')
        elif anomaly=='invalid_clock': raise OrchestrationError('invalid clock fields')
        if e['event']=='created' or e['from_state']==e['to_state']:
            if e['elapsed_ms'] is not None or (e['wall_time_ms'] is not None and anomaly is not None): raise OrchestrationError('duration/anomaly is not allowed for creation or unchanged state')
        elif e['wall_time_ms'] is not None:
            boundary=next((x for x in reversed(value['events'][:i-1]) if x['task_ref']==e['task_ref'] and x['to_state']==e['from_state'] and x['from_state']!=x['to_state']),None)
            if boundary is None or boundary['wall_time_ms'] is None:
                if e['elapsed_ms'] is not None or anomaly!='missing_stage_timestamp': raise OrchestrationError('missing stage boundary requires null duration and anomaly')
            elif e['wall_time_ms']<boundary['wall_time_ms']:
                if e['elapsed_ms'] is not None or anomaly!='backward_clock': raise OrchestrationError('backward clock requires null duration and anomaly')
            elif e['elapsed_ms']!=e['wall_time_ms']-boundary['wall_time_ms'] or anomaly is not None:
                raise OrchestrationError('duration does not match the prior state-entry boundary')
        if any(e.get(k) is not None for k in ('observed_model','observed_effort','observed_service_tier','observed_tokens','observed_cost','observed_ui_confirmation_count','observed_source','active_work_ms','human_wait_ms')): raise OrchestrationError('unavailable telemetry must be null')
        if e['contract_revision'] is None or e['contract_revision'] < 1 or e['attempt'] is None or e['review_round'] is None: raise OrchestrationError('required statistics counters cannot be null')
        defaults=ROLE_DEFAULTS.get(e['requested_role']) if e['requested_role'] else None
        if defaults and (e['canonical_model'],e['canonical_effort'])!=defaults: raise OrchestrationError('role defaults do not match the declared role')
        reviewed=e['event'] in {'review_pass','review_fail','review_inconclusive'}
        verified=e['event'] in {'integrated','completed'}
        if reviewed:
            if e['verification_result'] not in {'pass','fail','inconclusive'} or e['verification_source']!='manual_check_declaration': raise OrchestrationError('inconsistent verification fields')
            if e['verification_result'] != e['event'].removeprefix('review_'): raise OrchestrationError('review result does not match event')
        elif verified:
            if e['verification_result']!='pass' or e['verification_source']!='manual_check_declaration': raise OrchestrationError('inconsistent verification fields')
        elif e['verification_result'] is not None or e['verification_source'] is not None: raise OrchestrationError('verification fields are only allowed on verification events')
        if reviewed or verified:
            if type(e['verification_check_count']) is not int or type(e['verification_unrun_count']) is not int: raise OrchestrationError('verification counts are required')
        elif e['verification_check_count'] is not None or e['verification_unrun_count'] is not None or e['verification_source'] is not None: raise OrchestrationError('verification fields are only allowed on verification events')
        if e['elapsed_source']!='system_wall_clock_utc': raise OrchestrationError('elapsed source is required')
        last_by_task[e['task_ref']]=e
    return value

def log(db: dict[str, Any], task: Optional[dict[str, Any]], event: str, actor: str, **data: Any) -> None:
    stats_from_state=data.pop('_stats_from_state',None)
    db['history'].append({'time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'event': event, 'task': task['id'] if task else None, 'actor': actor, **data})
    if task is None or event not in STAT_EVENTS: return
    stats=db.get('statistics')
    if 'statistics' not in db: stats={'schema':1,'coverage':'legacy_partial','events':[]}; db['statistics']=stats
    validate_statistics(stats)
    events=stats['events']; now=time.time(); wall=None; anomaly=None
    try:
        if type(now) not in (int,float) or not (0 <= now*1000 <= 2**63-1): raise ValueError()
        wall=int(now*1000)
    except (ValueError,OverflowError): anomaly='invalid_clock'
    task_ref=_ref(task['id'],'orchestrator.stats.v1.task')
    prev=next((x for x in reversed(events) if x['task_ref']==task_ref),None)
    to_state=task.get('state'); from_state=None if event=='created' else stats_from_state
    elapsed=None
    if wall is not None and from_state is not None and from_state!=to_state:
        boundary=next((x for x in reversed(events) if x['task_ref']==task_ref and x['to_state']==from_state and x['from_state']!=x['to_state']),None)
        if boundary is None or boundary['wall_time_ms'] is None: anomaly='missing_stage_timestamp'
        elif wall<boundary['wall_time_ms']: anomaly='backward_clock'
        else: elapsed=wall-boundary['wall_time_ms']
    role=data.get('owner_role') or data.get('consultant_role') or data.get('reviewer_role')
    defaults=ROLE_DEFAULTS.get(role)
    verification=event.removeprefix('review_') if event.startswith('review_') else ('pass' if event in {'integrated','completed'} else None)
    participant=data.get('to_owner') or data.get('owner') or data.get('consultant_identity') or data.get('reviewer') or task.get('owner')
    event_row=dict(zip(STAT_KEYS,[len(events)+1,STAT_EVENTS[event],wall,_ref(task['id'],'orchestrator.stats.v1.task'),_ref(actor,'orchestrator.stats.v1.participant'),_ref(participant,'orchestrator.stats.v1.participant'),_ref(data.get('from_owner') or data.get('previous_owner'),'orchestrator.stats.v1.participant'),task.get('attempt',0),task.get('contract_revision',1),task.get('review_rounds',0),from_state,to_state,role,defaults[0] if defaults else None,defaults[1] if defaults else None,'manual_role_declaration' if role else None,None,None,None,None,None,None,None,verification,len(data.get('checks',[])) if verification else None,len(data.get('unrun',[])) if verification else None,'manual_check_declaration' if verification in {'pass','fail','inconclusive'} else None,elapsed,'system_wall_clock_utc',anomaly,None,None,None]))
    events.append(event_row)
    validate_statistics(stats)

def stats_report(db: dict[str, Any]) -> dict[str, Any]:
    stats=db.get('statistics')
    if 'statistics' not in db: stats={'schema':1,'coverage':'not_started','events':[]}
    else: validate_statistics(stats)
    events=stats['events']; bytype={}; byrole={}; attempts={}
    for e in events:
        bytype[e['event']]=bytype.get(e['event'],0)+1
        role=e['requested_role'] or 'unknown'; byrole[role]=byrole.get(role,0)+1
        attempts[e['task_ref']]=max(attempts.get(e['task_ref'],0),e['attempt'])
    return {'schema':1,'coverage':stats['coverage'],'clock_source':'system_wall_clock_utc','events':events,'summary':{'event_count':len(events),'task_count':len(attempts),'events_by_type':bytype,'events_by_role':byrole,'attempts_by_task':attempts},'visual':visual_statistics(db),'delivery_timing':{_ref(t['id'], 'orchestrator.stats.v1.task'):task_timing(t) for t in db['tasks'].values()}}

def cmd_stats(a: argparse.Namespace, root: Path) -> None:
    path=codex_dir(root)/DB_REL.name
    if _is_reparse_or_link(path): raise OrchestrationError('refusing unsafe backlog file')
    try: db=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc: raise OrchestrationError(f'cannot read backlog: {exc}')
    if not isinstance(db,dict) or db.get('schema')!=SCHEMA: raise OrchestrationError('unsupported backlog object or schema')
    report=stats_report(db); out=io.StringIO(newline='')
    if a.format=='json': json.dump(report,out,ensure_ascii=False,separators=(',',':')); out.write('\n')
    else:
        writer=csv.writer(out,lineterminator='\n'); writer.writerow(['schema','coverage',*STAT_KEYS])
        for row in report['events']: writer.writerow([1,report['coverage'],*[('' if row[k] is None else row[k]) for k in STAT_KEYS]])
    sys.stdout.write(out.getvalue())

def get_task(db: dict[str, Any], tid: str) -> dict[str, Any]:
    try: return db['tasks'][tid]
    except KeyError: raise OrchestrationError(f'unknown task: {tid}')

def owner(task: dict[str, Any], actor: str) -> None:
    if not actor or task.get('owner') != actor: raise OrchestrationError(f"owner mismatch: task owner is {task.get('owner')!r}, caller is {actor!r}")

def transition(task: dict[str, Any], target: str) -> None:
    if target not in TRANSITIONS.get(task['state'], set()): raise OrchestrationError(f"invalid transition {task['state']} -> {target}")
    task['state'] = target

def ready(db: dict[str, Any], task: dict[str, Any]) -> bool:
    return task['state'] == 'planned' and all(db['tasks'].get(x, {}).get('state') == 'completed' for x in task['depends_on'])

def active_tasks(db: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in db['tasks'].values() if t['state'] in {'assigned','in_progress','ready_for_review','interrupted','integrated'}]

def overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    # Empty/unknown scope is treated conservatively as globally shared.
    x, y = set(a['scope']), set(b['scope'])
    if not x or not y or '*' in x or '*' in y: return True
    return any(p == q or p.startswith(q.rstrip('/') + '/') or q.startswith(p.rstrip('/') + '/') for p in x for q in y)

def normalize_scope(raw: str, root: Path) -> list[str]:
    result=[]
    for item in raw.split(','):
        item=item.strip().replace('\\','/')
        if not item: continue
        if item.startswith('/') or (len(item)>1 and item[1]==':') or '..' in item.split('/'):
            raise OrchestrationError(f'unsafe scope path: {item!r}')
        # Windows projects are case-insensitive; fold everywhere so shared
        # work remains conservatively serialized across hosts.
        lexical='/'.join(part for part in item.split('/') if part not in ('','.'))
        resolved=(root / Path(lexical)).resolve(strict=False)
        try: lexical=resolved.relative_to(root.resolve()).as_posix()
        except ValueError: raise OrchestrationError(f'scope resolves outside project (possibly through symlink): {item!r}')
        result.append('*' if lexical == '.' else lexical.casefold())
    return sorted(set(result))

def cmd_init(a: argparse.Namespace, root: Path) -> None:
    codex_dir(root,create=True)
    with exclusive_lock(root/BOOTSTRAP_REL):
        selected_dir(root,a.data_dir)
        with locked(root):
            if (codex_dir(root) / 'ORCHESTRATOR.json').exists(): raise OrchestrationError('backlog already exists')
            db = empty_db(a.max_workers, a.review_round_limit, a.consultation_limit, a.escalation_limit); save(root, db)
    print(codex_dir(root) / 'ORCHESTRATOR.json')

def cmd_bind(a: argparse.Namespace, root: Path) -> None:
    base=root.resolve(); codex=codex_dir(root,create=True); target=safe_contained_path(root,a.data_dir)
    if target==codex: raise OrchestrationError('data directory must be distinct from legacy .codex')
    target.mkdir(parents=True,exist_ok=True); safe_contained_path(root,str(target))
    selector=root/SELECTOR_REL
    with exclusive_lock(root/BOOTSTRAP_REL):
        with exclusive_lock(codex/'ORCHESTRATOR.lock'):
            target=safe_contained_path(root,a.data_dir)
            if _is_reparse_or_link(selector): raise OrchestrationError('unsafe storage selector')
            if (codex/'ORCHESTRATOR.json').exists(): raise OrchestrationError('refusing to bind while legacy ledger exists')
            if selector.exists():
                old=selected_dir(root,None)
                if old!=target: raise OrchestrationError('project storage is already bound elsewhere')
                print(f'already bound: {old}'); return
            if (target/'ORCHESTRATOR.json').exists(): raise OrchestrationError('refusing to adopt an existing unbound ledger')
            payload=json.dumps({'schema':1,'data_dir':target.relative_to(base).as_posix()},indent=2)+'\n'
            try: fd=os.open(selector,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            except FileExistsError: raise OrchestrationError('storage selector appeared concurrently; retry')
            with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
    print(f'bound ledger storage: {target}')

def cmd_add(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root)
        if a.id in db['tasks']: raise OrchestrationError(f'task already exists: {a.id}')
        deps=[x for x in a.depends_on.split(',') if x]
        for dep in deps:
            if dep not in db['tasks']: raise OrchestrationError(f'unknown dependency: {dep}')
        if a.id in deps: raise OrchestrationError('task cannot depend on itself')
        if a.profile != 'code' and a.review_mode == 'manual-control': raise OrchestrationError('visual profiles require independent acceptance planning')
        if a.review_mode == 'manual-control' and a.risk != 'low': raise OrchestrationError('manual review control opt-out is limited to low-risk tasks')
        task={'id':a.id,'profile':a.profile,'goal':a.goal,'depends_on':deps,'priority':a.priority,'risk':a.risk,'scope':normalize_scope(a.scope,root), 'acceptance':a.acceptance,'contract_revision':1,'review_mode':a.review_mode,'acceptance_plans':[],'owner':None,'owner_history':[],'attempt':0,'state':'planned','review_rounds':0,'consultations':0,'evidence':[],'snapshot':None,'created_by':a.actor,'created_at':time.time()}
        task['approval_mode']=a.approval_mode
        if a.readiness: task['readiness']=readiness_contract(visual_json(a.readiness))
        db['tasks'][a.id]=task; log(db,task,'created',a.actor); save(root,db)
    print(a.id)

def cmd_list(a: argparse.Namespace, root: Path) -> None:
    db=load(root)
    for t in sorted(db['tasks'].values(),key=lambda x:(-x['priority'],x['id'])):
        print(f"{t['id']}\t{t['state']}\towner={t['owner'] or '-'}\trisk={t['risk']}\tready={str(ready(db,t)).lower()}\t{t['goal']}")

def cmd_assign(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if not ready(db,t): raise OrchestrationError('task is not ready; it must be planned and every dependency completed')
        require_acceptance_plan(t)
        for plan in t.get('acceptance_plans', []):
            if plan.get('contract_revision') == t.get('contract_revision') and a.owner == plan.get('reviewer'):
                raise OrchestrationError('planned acceptance reviewer cannot be assigned as task author')
        if any(x['owner']==a.owner and x['state'] in {'assigned','in_progress','ready_for_review','interrupted','integrated'} for x in active_tasks(db)): raise OrchestrationError(f'owner {a.owner} already has an active task')
        act=active_tasks(db)
        if len(act)>=db['config']['max_workers']: raise OrchestrationError('configured max_workers reached')
        conflicts=[x['id'] for x in act if overlaps(x,t)]
        if conflicts: raise OrchestrationError('scope conflicts with active task(s): '+', '.join(conflicts))
        prior=t['state']; t['owner']=a.owner; t['owner_role']=a.owner_role; t['owner_history'].append(a.owner); t['assigned_snapshot']=snapshot(root); transition(t,'assigned'); log(db,t,'assigned',a.actor,owner=a.owner,owner_role=a.owner_role,_stats_from_state=prior); save(root,db)
    print(a.id)

def cmd_state(a: argparse.Namespace, root: Path, target: str) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id); owner(t,a.actor)
        if target == 'in_progress':
            require_acceptance_plan(t)
        if target == 'ready_for_review' and t.get('profile', 'code') in VISUAL_PROFILES:
            require_visual_production(root,t)
            if not visual_task(t).get('artifacts'): raise OrchestrationError('final visual artifacts required before submission')
            visual_files_current(root,visual_task(t)['artifacts'])
            visual_task(t)['stage']='qa'
        prior=t['state']; transition(t,target)
        if target == 'ready_for_review': t.setdefault('first_submitted_at',time.time()); t['last_submitted_at']=time.time()
        if target == 'in_progress':
            t['attempt'] = int(t.get('attempt', 0)) + 1
            t.pop('review_snapshot', None)
            if t.get('visual',{}).get('stage') in {'qa','delivery'}: t['visual']['stage']='production'
        log(db,t,target,a.actor,attempt=t.get('attempt'),owner_role=t.get('owner_role'),_stats_from_state=prior); save(root,db)

def cmd_replan(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if a.actor != a.director: raise OrchestrationError('only the director may re-plan a task')
        if t['state'] not in {'planned', 'blocked'}:
            raise OrchestrationError('replan requires planned or blocked state with no active worker reservation; interrupt and recover a running worker first')
        if t.get('diagnosis_required'):
            if not a.diagnosis or not a.changed_approach: raise OrchestrationError('repeated criterion failure requires diagnosis and changed approach')
            t.setdefault('diagnoses',[]).append({'cause':a.diagnosis,'changed_approach':a.changed_approach,'time':time.time()})
            t['diagnosis_required']=False
        prior=t['state']; t['state']='planned'; t['owner']=None; t['director_resolution']=a.reason
        changed={}
        if a.goal is not None: changed['goal']={'old':t['goal'],'new':a.goal}; t['goal']=a.goal
        if a.acceptance is not None: changed['acceptance']={'old':t['acceptance'],'new':a.acceptance}; t['acceptance']=a.acceptance
        if a.scope is not None: changed['scope']={'old':t['scope'],'new':normalize_scope(a.scope,root)}; t['scope']=changed['scope']['new']
        if changed:
            t['contract_revision'] = int(t.get('contract_revision', 1)) + 1
            for plan in t.get('acceptance_plans', []):
                if plan.get('contract_revision') < t['contract_revision']:
                    plan['invalidated'] = True
        log(db,t,'replanned',a.actor,reason=a.reason,contract_changes=changed,contract_revision=t['contract_revision'],_stats_from_state=prior); save(root,db)

def require_acceptance_plan(task: dict[str, Any]) -> None:
    if task.get('review_mode') == 'manual-control':
        if task.get('profile', 'code') in VISUAL_PROFILES: raise OrchestrationError('visual profiles cannot bypass independent acceptance planning')
        if task.get('risk') != 'low':
            raise OrchestrationError('manual review control is permitted only for low-risk tasks')
        return
    current = [plan for plan in task.get('acceptance_plans', [])
               if plan.get('contract_revision') == task.get('contract_revision') and not plan.get('invalidated')]
    if not current:
        raise OrchestrationError('independent acceptance plan for the current contract is required before assignment/start')

def cmd_plan_review(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if t['state'] != 'planned' or t.get('owner'):
            raise OrchestrationError('acceptance planning must happen before assignment and implementation')
        if a.actor != a.director:
            raise OrchestrationError('only the director records an acceptance plan')
        if a.contract_version != str(t.get('contract_revision', 1)):
            raise OrchestrationError('acceptance plan contract version must match the current contract revision')
        if not a.fresh_context_attested or not PLAN_CONTEXT_ITEMS.issubset(set(a.context_item)):
            raise OrchestrationError('fresh-context manual attestation must include contract, diff, relevant-code, and verification-results; actor IDs and attestations are not authentication')
        if a.reviewer in set(t.get('owner_history', [])):
            raise OrchestrationError('acceptance planner must be independent of every task author')
        plan={'reviewer':a.reviewer,'contract_revision':t.get('contract_revision',1),
              'contract':{'goal':t['goal'],'scope':t['scope'],'acceptance':t['acceptance']},
              'scenarios':a.scenario,'context_items':sorted(set(a.context_item)),
              'fresh_context_attested':True,'identity_is_manual_attestation':True,
              'snapshot':snapshot(root),'status':'planned','time':time.time()}
        prior=t['state']; t.setdefault('acceptance_plans',[]).append(plan)
        log(db,t,'acceptance_plan_recorded',a.actor,reviewer=a.reviewer,reviewer_role=a.reviewer_role,contract_revision=plan['contract_revision'],snapshot=plan['snapshot']['fingerprint'],_stats_from_state=prior)
        save(root,db)

def cmd_escalate(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if a.actor != a.director: raise OrchestrationError('only the director may escalate a task')
        if t['state'] not in {'in_progress','ready_for_review'}: raise OrchestrationError('only an active implementation or submitted task can be escalated')
        if t['review_rounds'] < db['config']['review_round_limit']: raise OrchestrationError('escalation requires exhausting the configured Luna review/correction rounds')
        if t.get('escalations',0) >= db['config']['escalation_limit']: raise OrchestrationError('escalation allowance exhausted; director must create a separate follow-up task')
        if not a.reason.strip() or not a.context.strip(): raise OrchestrationError('escalation needs a rationale plus reproduction and prior-attempt context')
        if not a.old_agent_interrupted: raise OrchestrationError('director must explicitly declare the previous owner stopped with --old-agent-interrupted before reassignment; this manual declaration is not authentication or proof that a process was killed')
        owner_model=ROLE_MODELS.get(a.owner_role)
        if not owner_model or owner_model!='gpt-6.1-sol': raise OrchestrationError('senior escalation must route through canonical sol_senior pinned to gpt-6.1-sol')
        if a.owner in set(t.get('owner_history', [])): raise OrchestrationError('escalation requires a new independent Sol instance identity')
        if any(plan.get('contract_revision') == t.get('contract_revision', 1)
               and not plan.get('invalidated') and plan.get('reviewer') == a.owner
               for plan in t.get('acceptance_plans', [])):
            raise OrchestrationError('current acceptance planner cannot become the escalated task author; choose an independent owner')
        if any(x['owner']==a.owner and x['state'] in {'assigned','in_progress','ready_for_review','interrupted','integrated'} for x in active_tasks(db) if x['id'] != t['id']): raise OrchestrationError(f'new owner {a.owner} already has an active task')
        prior=t['state']; old=t['owner']; old_attempt=t.get('attempt',0)
        transition(t,'assigned')
        t['previous_owner']=old; t['owner']=a.owner; t['owner_role']=a.owner_role; t.setdefault('owner_history',[]).append(a.owner)
        t['escalations']=t.get('escalations',0)+1; t.setdefault('escalation_history',[]).append({'from':old,'to':a.owner,'owner_role':a.owner_role,'model':owner_model,'identity_is_manual_attestation':'true','previous_owner_stopped_manual_attestation':True,'previous_attempt':old_attempt,'next_start_attempt':old_attempt+1,'reason':a.reason,'context':a.context,'director':a.actor,'time':time.time()})
        log(db,t,'escalated',a.actor,from_owner=old,to_owner=a.owner,owner_role=a.owner_role,model=owner_model,previous_owner_stopped_manual_attestation=True,previous_attempt=old_attempt,next_start_attempt=old_attempt+1,reason=a.reason,context=a.context,_stats_from_state=prior); save(root,db)

def cmd_recover(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if t['state']!='interrupted': raise OrchestrationError('only interrupted tasks can be recovered')
        if not a.old_agent_interrupted: raise OrchestrationError('director must explicitly declare the old owner stopped with --old-agent-interrupted; this manual declaration is not authentication or proof that a process was killed')
        prior=t['state']; old=t['owner']
        if old==a.owner: raise OrchestrationError('recovery requires a new owner identity')
        if any(plan.get('contract_revision') == t.get('contract_revision', 1)
               and not plan.get('invalidated') and plan.get('reviewer') == a.owner
               for plan in t.get('acceptance_plans', [])):
            raise OrchestrationError('current acceptance planner cannot become the recovered task author; choose an independent owner')
        if any(x['owner']==a.owner and x['state'] in {'assigned','in_progress','ready_for_review','interrupted','integrated'} for x in active_tasks(db) if x['id'] != t['id']): raise OrchestrationError(f'new owner {a.owner} already has an active task')
        t['previous_owner']=old; t['owner']=a.owner; t['owner_role']=a.owner_role; t.setdefault('owner_history',[]).append(a.owner); t['recovery_context']=a.context; t['state']='assigned'; t['assigned_snapshot']=snapshot(root)
        log(db,t,'recovered',a.actor,previous_owner=old,owner=a.owner,owner_role=a.owner_role,context=a.context,_stats_from_state=prior); save(root,db)

def cmd_review(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if t['state']!='ready_for_review': raise OrchestrationError('task is not ready for review')
        require_acceptance_plan(t)
        if not a.fresh_context_attested or not PLAN_CONTEXT_ITEMS.issubset(set(a.context_item)):
            raise OrchestrationError('fresh-context manual attestation must include contract, diff, relevant-code, and verification-results; actor IDs and attestations are not authentication')
        if a.reviewer == t['created_by']: raise OrchestrationError('reviewer must be independent of director claims')
        if a.reviewer in set(t.get('owner_history', [t['owner']])): raise OrchestrationError('reviewer must be distinct from every task author')
        if t['review_rounds']>=db['config']['review_round_limit'] + t.get('escalations',0): raise OrchestrationError('review round allowance reached; director must re-evaluate or create a follow-up task')
        if a.result == 'pass' and a.unrun: raise OrchestrationError('unrun checks are NOT VERIFIED; pass refused')
        if a.result == 'pass' and (not a.check or any(not check_passed(c) for c in a.check)):
            raise OrchestrationError('pass requires each --check as PASS; command=...; result=exit 0|passed; evidence=...')
        if a.result == 'pass':
            require_visual_qa(root,t)
            if t.get('readiness'):
                if not a.readiness_evidence: raise OrchestrationError('readiness evidence required')
                require_readiness(t, visual_json(a.readiness_evidence), a.reviewer, snapshot(root))
        senior_evidence=senior_role_evidence(a, t)
        astra_resolution=astra_resolution_evidence(a,t)
        review_from_state=t['state']; review_snapshot=snapshot(root)
        evidence={'visual_signature':visual_signature(t),'reviewer':a.reviewer,'result':a.result,'checks':a.check,'unrun':a.unrun,'findings':a.findings,'senior_verifier':senior_evidence,'astra_resolution':astra_resolution,'fresh_context':{'attested':True,'items':sorted(set(a.context_item)),'identity_is_manual_attestation':True},'contract_revision':t.get('contract_revision',1),'attempt':t.get('attempt',0),'owner_history_digest':owner_history_digest(t),'time':time.time(),'snapshot':review_snapshot}
        if a.result != 'pass' and a.readiness_evidence:
            require_readiness(t, visual_json(a.readiness_evidence), a.reviewer, review_snapshot, allow_unverified=True)
        if a.result == 'fail' and t.get('readiness') and not a.defects: raise OrchestrationError('failed readiness review requires unified defects')
        if a.defects:
            record_defects(t, defect_json(a.defects))
        t['review_rounds']+=1; t['evidence'].append(evidence); t['review_snapshot']=review_snapshot
        if a.result=='pass':
            if any(d['status'] != 'fixed' for d in current_defects(t)): raise OrchestrationError('unresolved defects prevent PASS')
            if t['risk'] in {'high','critical'} and not (a.senior_verified or astra_resolution): raise OrchestrationError('high risk needs canonical read-only Sol reviewer verification or recorded canonical Astra consultation with director resolution')
        else:
            target='in_progress' if a.result=='fail' and not t.get('diagnosis_required') else 'blocked'
            transition(t,target)
            if t.get('visual') and a.result=='fail': t['visual']['stage']='production'
        log(db,t,'review_'+a.result,a.reviewer,checks=a.check,unrun=a.unrun,findings=a.findings,reviewer_role=a.reviewer_role,reviewer=a.reviewer,_stats_from_state=review_from_state); save(root,db)

def cmd_integrate(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if t['state']!='ready_for_review' or not current_review(t): raise OrchestrationError('current passing review evidence required before integration')
        require_acceptance_plan(t)
        require_visual_qa(root,t)
        reviewer=t['evidence'][-1]['reviewer']
        if reviewer in set(t.get('owner_history', [])) | {t['created_by']}:
            raise OrchestrationError('recorded reviewer is no longer independent of every task author')
        senior_evidence=senior_role_evidence(a, t)
        astra_used=astra_resolution_evidence(a,t)
        if t['risk'] in {'high','critical'} and not (senior_evidence or astra_used): raise OrchestrationError('high risk requires canonical read-only Sol reviewer verification or recorded canonical Astra consultation with director resolution')
        current=snapshot(root)
        if current!=t['review_snapshot']: raise OrchestrationError('review snapshot is stale; re-review the current combined tree')
        if not a.check or any(not check_passed(c) for c in a.check): raise OrchestrationError('integrated-state verification requires --check formatted PASS; command=...; result=exit 0|passed; evidence=...')
        prior=t['state']; t['state']='integrated'; t['integrated_snapshot']=current; t['integration_evidence']={'actor':a.actor,'checks':a.check,'senior_verifier':senior_evidence,'astra_resolution':astra_used,'time':time.time()}
        log(db,t,'integrated',a.actor,snapshot=current,checks=a.check,_stats_from_state=prior); save(root,db)

def cmd_complete(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if t['state']!='integrated': raise OrchestrationError('task must be integrated first')
        if any(d['status'] != 'fixed' for d in current_defects(t)): raise OrchestrationError('unresolved defects prevent completion')
        if not t.get('evidence') or not current_review(t): raise OrchestrationError('current passing review evidence is required at completion')
        if t['evidence'][-1]['reviewer'] in set(t.get('owner_history', [])) | {t['created_by']}:
            raise OrchestrationError('recorded reviewer is no longer independent of every task author')
        require_visual_qa(root,t)
        if snapshot(root)!=t['integrated_snapshot']: raise OrchestrationError('integrated snapshot is stale; completion refused')
        if not a.check or any(not check_passed(c) for c in a.check): raise OrchestrationError('completion verification requires --check formatted PASS; command=...; result=exit 0|passed; evidence=...')
        prior=t['state']; t['state']='completed'
        if t.get('profile', 'code') in VISUAL_PROFILES:
            t['visual']['stage']='delivery'; visual_event(t['visual'],'delivered','initial')
        log(db,t,'completed',a.actor,checks=a.check,_stats_from_state=prior); save(root,db)

def cmd_consult(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if a.actor != a.director: raise OrchestrationError('only the director records a consultation')
        if t['consultations'] >= db['config']['consultation_limit']: raise OrchestrationError('consultation limit reached; director must resolve or defer')
        if not a.consultant.strip(): raise OrchestrationError('consultant instance identity is required')
        if a.consultant == a.actor or a.consultant in set(t.get('owner_history', [])): raise OrchestrationError('consultant identity must be distinct from the director and every task author')
        model=ROLE_MODELS.get(a.consultant_role)
        if not model: raise OrchestrationError(f'unsupported consultant role: {a.consultant_role}')
        record={'question':a.question,'budget':a.budget,'outcome':a.outcome,'time':time.time(),'consultant_identity':a.consultant,'consultant_role':a.consultant_role,'model':model,'identity_is_manual_attestation':'true'}
        t['consultations']+=1; t.setdefault('consultation_evidence',[]).append(record)
        log(db,t,'consultation_recorded',a.actor,_stats_from_state=t['state'],**record); save(root,db)

def check_passed(evidence: str) -> bool:
    """Require an explicit, unambiguous manual attestation of a passed check."""
    match = re.fullmatch(r'PASS;\s*command=(.+);\s*result=(exit 0|passed);\s*evidence=(.+)', evidence.strip(), re.IGNORECASE)
    return bool(match and match.group(1).strip() and match.group(3).strip())

def owner_history_digest(task: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(task.get('owner_history', []), ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def current_review(task: dict[str, Any]) -> bool:
    if not task.get('evidence'):
        return False
    evidence=task['evidence'][-1]
    return (evidence.get('result') == 'pass'
            and evidence.get('contract_revision') == task.get('contract_revision', 1)
            and evidence.get('attempt') == task.get('attempt', 0)
            and evidence.get('visual_signature') == visual_signature(task)
            and evidence.get('owner_history_digest') == owner_history_digest(task)
            and evidence.get('snapshot') == task.get('review_snapshot'))

def independent_reviewer_identity(args: argparse.Namespace, task: dict[str, Any]) -> Optional[str]:
    """Use the current Luna identity at review and the recorded one at integration."""
    reviewer=getattr(args,'reviewer',None)
    if reviewer is None and task.get('evidence'):
        reviewer=task['evidence'][-1].get('reviewer')
    return reviewer

def senior_role_evidence(args: argparse.Namespace, task: dict[str, Any]) -> Optional[dict[str, str]]:
    if not args.senior_verified:
        if args.senior_reviewer or args.senior_role: raise OrchestrationError('senior identity/role requires --senior-verified')
        return None
    identity=args.senior_reviewer
    role=args.senior_role
    if not identity or not identity.strip() or not role:
        raise OrchestrationError('--senior-verified requires --senior-reviewer ID and --senior-role sol_reviewer')
    model=ROLE_MODELS.get(role)
    if role != 'sol_reviewer' or model != 'gpt-6.1-sol':
        raise OrchestrationError('independent review verification must use canonical read-only sol_reviewer pinned to gpt-6.1-sol')
    if identity in set(task.get('owner_history', [task['owner']])):
        raise OrchestrationError('senior verifier must be independent of every task author')
    reviewer=independent_reviewer_identity(args,task)
    if identity==reviewer: raise OrchestrationError('senior verifier must be a separate instance from the Luna reviewer')
    return {'identity':identity,'role':role,'model':model,'read_only':True,'identity_is_manual_attestation':'true'}

def has_astra_consultation(task: dict[str, Any]) -> bool:
    return any(x.get('consultant_role')=='astra_consultant' and x.get('model')=='gpt-6-astra' for x in task.get('consultation_evidence', []))

def astra_resolution_evidence(args: argparse.Namespace, task: dict[str, Any]) -> Optional[dict[str,str]]:
    if not args.astra_consulted and not args.director_resolved and not args.director_decision: return None
    if not (args.astra_consulted and has_astra_consultation(task) and args.director_resolved and args.director_decision.strip()):
        raise OrchestrationError('Astra reliance requires recorded canonical consultation plus director resolution and --director-decision')
    reviewer=independent_reviewer_identity(args,task)
    authors=set(task.get('owner_history',[task['owner']]))
    eligible=[record for record in task.get('consultation_evidence',[])
              if record.get('consultant_role')=='astra_consultant'
              and record.get('model')==ROLE_MODELS['astra_consultant']
              and record.get('consultant_identity')
              and record['consultant_identity'] not in authors
              and record['consultant_identity'] != reviewer]
    if not eligible:
        raise OrchestrationError('Astra consultant must be independent of every task author and a separate instance from the Luna reviewer')
    record=eligible[-1]
    return {'consultant_identity':record['consultant_identity'],'consultant_role':'astra_consultant',
            'model':ROLE_MODELS['astra_consultant'],'director_decision':args.director_decision,
            'identity_is_manual_attestation':'true'}

# Visual profiles extend the same manual ledger; they do not launch tools or models.
VISUAL_PROFILES = {'visual-design', 'ux-ui', 'storyboard', 'motion-fx'}
VISUAL_CAPABILITIES = {'reference_search', 'image_inspection', 'editable_export', 'preview_export',
                       'custom_roles', 'image_generation', 'video_generation',
                       'browser_interaction', 'temporal_inspection'}
VISUAL_REASONS = {'initial', 'user-feedback', 'direction-change', 'capability-change',
                  'qa-fix', 'scope-change', 'recovery'}


def visual_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     separators=(',', ':')).encode()).hexdigest()


def visual_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrchestrationError(f'visual {name} must be a nonempty string')
    return value


def visual_object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict): raise OrchestrationError(f'visual {name} must be an object')
    return value


def visual_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list) or not value: raise OrchestrationError(f'visual {name} must be a nonempty list')
    return value


def visual_json(path: str) -> dict[str, Any]:
    try: value = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc: raise OrchestrationError(f'cannot read visual JSON: {exc}') from exc
    return visual_object(value, 'input')


def readiness_contract(value: Any) -> dict[str, Any]:
    contract = visual_object(value, 'readiness contract')
    for key in ('functional', 'user'):
        for criterion in visual_list(contract.get(key), key + ' criteria'): visual_text(criterion, key)
    for key in ('visual', 'audio', 'performance', 'device'):
        entry = visual_object(contract.get(key), key)
        if type(entry.get('relevant')) is not bool: raise OrchestrationError(key + ' needs relevant boolean')
        visual_text(entry.get('criteria') if entry['relevant'] else entry.get('reason'), key + ' criteria/reason')
    visual_text(contract.get('target'), 'target device/environment')
    visual_list(contract.get('checks'), 'planned checks')
    if 'launch' in contract:
        launch=visual_object(contract['launch'], 'launch instructions')
        if launch.get('status') == 'available':
            for step in visual_list(launch.get('instructions'), 'launch instructions'): visual_text(step, 'launch instruction')
        elif launch.get('status') == 'unavailable': visual_text(launch.get('reason'), 'launch unavailable reason')
        else: raise OrchestrationError('launch status must be available or unavailable')
    return contract


def require_readiness(task, evidence, reviewer, current, allow_unverified=False):
    if evidence.get('reviewer') != reviewer or reviewer in set(task.get('owner_history', [])) | {task['created_by']}:
        raise OrchestrationError('readiness evidence needs an independent reviewer')
    if evidence.get('snapshot') != current['fingerprint'] or evidence.get('contract_revision') != task['contract_revision'] or evidence.get('attempt') != task['attempt']:
        raise OrchestrationError('readiness evidence is stale')
    checks = visual_object(evidence.get('checks'), 'readiness checks')
    if set(checks) != {'functional','user','visual','audio','performance','device'}:
        raise OrchestrationError('readiness checks must contain exactly the six declared categories; unknown checks are not accepted')
    for name in ('functional', 'user', 'visual', 'audio', 'performance', 'device'):
        check = visual_object(checks.get(name), name + ' check')
        relevant = name in ('functional', 'user') or task['readiness'][name]['relevant']
        expected = 'pass' if relevant else 'not_applicable'
        if relevant and allow_unverified and check.get('result') in ('not_verified','fail'):
            visual_text(check.get('reason'), name + ' unavailable/failure reason')
            continue
        if check.get('result') != expected:
            raise OrchestrationError(name + ' is NOT VERIFIED; record unavailable reason, never claim a pass')
        for key in (('tool','source','observation') if relevant else ('reason',)):
            visual_text(check.get(key), name + ' ' + key)
    task['readiness_evidence'] = dict(evidence, owner_history_digest=owner_history_digest(task))


def require_slice(task, selection):
    early = visual_object(selection.get('finished_slice'), 'early finished slice')
    required = ['keyframe','reference_comparison']
    if task['profile'] == 'ux-ui': required.append('main_flow')
    if task.get('readiness',{}).get('audio',{}).get('relevant'): required.append('audio')
    for name in required:
        check=visual_object(early.get(name),name + ' observation')
        if check.get('result') != 'pass':
            visual_text(check.get('reason'),name + ' NOT VERIFIED reason')
            raise OrchestrationError(name + ' is NOT VERIFIED; production blocked')
        for key in ('tool','source','observation'): visual_text(check.get(key),name + ' ' + key)


def selection_source(task, value):
    evidence = visual_object(value, 'selection evidence')
    if task.get('approval_mode', 'explicit-user') == 'explicit-user' or evidence.get('origin') == 'user':
        return visual_source(evidence)
    if evidence.get('observer_origin') != 'independent-reviewer': raise OrchestrationError('observations must originate with an independent reviewer')
    if evidence.get('decision') != 'accepted' or evidence.get('origin') != 'observed':
        raise OrchestrationError('observed selection needs accepted decision and observed origin')
    if evidence.get('reviewer') in set(task.get('owner_history', [])) | {task['created_by']}:
        raise OrchestrationError('observed acceptance needs independent reviewer evidence')
    for key in ('reviewer', 'tool', 'source', 'observation'): visual_text(evidence.get(key), key)
    return evidence


def defect_json(path):
    try: return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc: raise OrchestrationError(f'cannot read defect evidence: {exc}') from exc


def record_defects(task, records):
    if not isinstance(records, list) or not records: raise OrchestrationError('defects must be a nonempty list')
    history = task.setdefault('defects', [])
    for raw in records:
        defect = dict(visual_object(raw, 'defect'))
        for key in ('id','criterion','priority','reproduction','cause','owner','status'): visual_text(defect.get(key), 'defect ' + key)
        if defect['priority'] not in ('P0','P1','P2','P3'): raise OrchestrationError('defect priority must be P0-P3')
        if defect['status'] not in ('open','fixed','not_verified'): raise OrchestrationError('invalid defect status')
        if defect['status'] == 'open' and any(d['criterion'] == defect['criterion'] and d['status'] == 'open' for d in current_defects(task)):
            task['diagnosis_required'] = True
        defect.update({'attempt':task['attempt'],'time':time.time()})
        history.append(defect)


def current_defects(task):
    latest={}
    for defect in task.get('defects',[]): latest[(defect['id'],defect['criterion'])]=defect
    return list(latest.values())


def result_passport(task, current=None):
    fingerprint = current.get('fingerprint') if current else None
    authors = set(task.get('owner_history', [])) | {task['created_by']}
    def matches(record, readiness=False):
        snap = record.get('snapshot')
        snap = snap if readiness else (snap or {}).get('fingerprint')
        return bool(fingerprint and snap == fingerprint
                    and record.get('contract_revision') == task.get('contract_revision',1)
                    and record.get('attempt') == task.get('attempt',0)
                    and record.get('owner_history_digest') == owner_history_digest(task)
                    and record.get('reviewer') not in authors)
    reports=task.get('evidence',[])
    current_reports=[reports[-1]] if reports and matches(reports[-1]) else []
    stale_reports=reports[:-1] if current_reports else reports
    accepted=bool(task['state'] in {'ready_for_review','integrated','completed'}
                  and current_review(task) and reports and matches(reports[-1]))
    readiness=task.get('readiness_evidence')
    valid_readiness=readiness if accepted and readiness and matches(readiness,True) else None
    not_verified=[]
    if readiness and not valid_readiness: not_verified.append('readiness evidence is stale or has no current passing independent review')
    elif not readiness: not_verified.append('readiness evidence unavailable')
    if not accepted: not_verified.append('current independent acceptance NOT VERIFIED')
    if valid_readiness:
        not_verified.extend(name + ': ' + check.get('reason','unavailable') for name,check in valid_readiness.get('checks',{}).items() if check.get('result') in {'not_verified','fail','inconclusive'})
    not_verified.extend(u for report in current_reports for u in report.get('unrun',[]))
    qa=task.get('visual',{}).get('qa')
    return {'task':task['id'],'state':task['state'],'contract':task.get('readiness',task['acceptance']),
            'contract_revision':task.get('contract_revision',1),'attempt':task.get('attempt',0),
            'artifacts':task.get('visual',{}).get('artifacts',[]),
            'evidence_freshness':{'snapshot':fingerprint,'current_acceptance':accepted,'readiness_current':bool(valid_readiness)},
            'independent_evidence':{'readiness':valid_readiness,'reviews':current_reports,'visual_qa':qa if accepted else None},
            'historical_evidence':{'readiness':readiness if not valid_readiness else None,'reviews':stale_reports,'visual_qa':qa if not accepted else None},
            'worker_reports':'separate from independent evidence','defects':current_defects(task),
            'not_verified':not_verified,
            'limitations':['Manual records do not prove tool execution, device use, listening, identity or model usage'],
            'launch':task.get('readiness',{}).get('launch',{'status':'unavailable','reason':'Actual launch instructions were not recorded'}),
            'planned_checks':task.get('readiness',{}).get('checks',[]),
            'timing':task_timing(task),'observed_model_usage':None}


def task_timing(task):
    first=task.get('first_submitted_at'); last=task.get('last_submitted_at'); created=task.get('created_at')
    def elapsed(start,end):
        if type(start) not in (int,float) or type(end) not in (int,float): return None
        if not (float('-inf') < start <= end < float('inf')): return None
        return end-start
    return {'first_version_elapsed_seconds':elapsed(created,first),
            'rework_elapsed_seconds':elapsed(first,last),
            'source':'manual ledger wall time; not active model time or cost'}


def visual_source(value: Any) -> dict[str, Any]:
    evidence = visual_object(value, 'approval evidence')
    if evidence.get('decision') != 'approved' or evidence.get('origin') != 'user':
        raise OrchestrationError('explicit user approval required; agent approval or a PASS is insufficient')
    for key in ('source', 'quote', 'approved_by'):
        visual_text(evidence.get(key), f'approval {key}')
    return evidence


def visual_file(root: Path, value: Any) -> dict[str, Any]:
    item = visual_object(value, 'artifact')
    path = visual_text(item.get('path'), 'artifact path')
    visual_text(item.get('format'), 'artifact format')
    candidate = safe_contained_path(root, path)
    if not candidate.is_file(): raise OrchestrationError(f'visual artifact missing: {path}')
    # Snapshot bytes even for ignored outputs. No claim is made about their pixels.
    record = dict(item)
    record['path'] = candidate.relative_to(root).as_posix()
    record['content'] = worktree_value(root, record['path'])
    return record


def visual_files_current(root: Path, items: list[dict[str, Any]]) -> None:
    for item in items:
        current = visual_file(root, item)
        if current['content'] != item.get('content'):
            raise OrchestrationError(f"visual artifact evidence is stale: {item['path']}")


def visual_task(task: dict[str, Any]) -> dict[str, Any]:
    if task.get('profile', 'code') not in VISUAL_PROFILES:
        raise OrchestrationError('visual command requires a visual task profile')
    if not isinstance(task.get('visual'), dict): raise OrchestrationError('visual spec is required')
    return task['visual']


def visual_binding(task: dict[str, Any]) -> dict[str, Any]:
    v = visual_task(task)
    return {'revision': v['revision'], 'spec_digest': visual_digest(v['spec']),
            'contract_revision': task.get('contract_revision', 1)}


def visual_signature(task: dict[str, Any]) -> Optional[str]:
    if task.get('profile', 'code') not in VISUAL_PROFILES: return None
    visual = task.get('visual') or {}
    return visual_digest({key: visual.get(key) for key in ('revision', 'spec', 'boards', 'preflight', 'approvals', 'prototype', 'artifacts', 'qa')})


def visual_current(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    v = visual_task(task)
    visual_files_current(root, v['boards'])
    return v


def visual_required(task: dict[str, Any]) -> set[str]:
    required = {'reference_search', 'image_inspection', 'editable_export', 'preview_export', 'custom_roles'}
    if task['profile'] == 'ux-ui': required.add('browser_interaction')
    if task['profile'] == 'motion-fx': required.add('temporal_inspection')
    return required | set(visual_task(task)['spec'].get('required_capabilities', []))


def visual_preflight(root: Path, task: dict[str, Any]) -> None:
    v = visual_current(root, task)
    record = v.get('preflight') or {}
    if record.get('binding') != visual_binding(task): raise OrchestrationError('current visual capability preflight required')
    missing = [name for name in sorted(visual_required(task))
               if record.get('capabilities', {}).get(name, {}).get('status') != 'available']
    if missing: raise OrchestrationError('visual capability blockers: ' + ', '.join(missing))


def visual_approval(root: Path, task: dict[str, Any], target: str) -> dict[str, Any]:
    v = visual_current(root, task)
    record = v.get('approvals', {}).get(target) or {}
    if record.get('binding') != visual_binding(task): raise OrchestrationError(f'current user {target} approval required')
    selection_source(task, record)
    if target == 'prototype':
        visual_files_current(root, v.get('prototype', []))
        if not v.get('prototype') or record.get('artifact_digest') != visual_digest(v['prototype']):
            raise OrchestrationError('prototype approval is stale')
        if record.get('direction_digest') != visual_digest(v['approvals'].get('direction')):
            raise OrchestrationError('prototype approval belongs to another direction')
    return record


def require_visual_production(root: Path, task: dict[str, Any]) -> None:
    if task.get('profile', 'code') not in VISUAL_PROFILES: return
    visual_preflight(root, task)
    visual_approval(root, task, 'direction'); visual_approval(root, task, 'prototype')
    if visual_task(task)['stage'] not in {'production', 'qa', 'delivery'}:
        raise OrchestrationError('explicit visual-production transition required before production/submission')


def require_visual_qa(root: Path, task: dict[str, Any]) -> None:
    if task.get('profile', 'code') not in VISUAL_PROFILES: return
    require_visual_production(root, task)
    v = visual_task(task)
    if not v.get('artifacts'): raise OrchestrationError('editable sources, preview, and report required')
    visual_files_current(root, v['artifacts'])
    qa = v.get('qa') or {}
    if (qa.get('binding') != visual_binding(task) or qa.get('result') != 'pass'
            or qa.get('artifact_digest') != visual_digest(v['artifacts'])
            or qa.get('direction_digest') != visual_digest(v['approvals'])
            or qa.get('owner_history_digest') != owner_history_digest(task)
            or qa.get('attempt') != task.get('attempt', 0)):
        raise OrchestrationError('current independent visual QA required; text PASS is insufficient')
    if qa.get('reviewer') in set(task.get('owner_history', [])) | {task.get('created_by')}:
        raise OrchestrationError('visual QA reviewer must be independent of authors and director')


def visual_event(v: dict[str, Any], event: str, reason: str, **details: Any) -> None:
    v.setdefault('events', []).append({'event': event, 'stage': v['stage'], 'revision': v['revision'],
                                      'reason': reason, 'time': time.time(), **details})


def validate_visual_spec(root: Path, profile: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    brief = visual_object(spec.get('brief'), 'brief')
    for key in ('idea', 'audience'): visual_text(brief.get(key), f'brief {key}')
    for item in visual_list(brief.get('constraints'), 'constraints'): visual_text(item, 'constraint')
    refs = visual_list(spec.get('references'), 'references')
    ids = set()
    for raw in refs:
        ref = visual_object(raw, 'reference')
        rid = visual_text(ref.get('id'), 'reference id')
        if rid in ids: raise OrchestrationError('duplicate visual reference id')
        ids.add(rid)
        for key in ('url', 'take', 'avoid', 'inspection_source'): visual_text(ref.get(key), f'reference {key}')
        if not re.match(r'^https?://[^/\s]+(?:/|$)', ref['url']): raise OrchestrationError('reference needs an HTTP(S) source link')
    existing = spec.get('existing_style')
    if existing is not None:
        visual_object(existing, 'existing style')
        for key in ('source', 'version', 'scope'): visual_text(existing.get(key), f'existing style {key}')
        visual_source(existing.get('approval'))
    if 'scope_reduction' in spec:
        reduction = visual_object(spec['scope_reduction'], 'scope reduction')
        visual_text(reduction.get('description'), 'scope reduction description'); visual_source(reduction.get('approval'))
    directions = visual_list(spec.get('directions'), 'directions')
    if not (len(directions) == 1 if existing else 2 <= len(directions) <= 3):
        raise OrchestrationError('provide 2–3 coherent directions, or one explicitly approved existing style')
    boards = []; direction_ids = set()
    for raw in directions:
        direction = visual_object(raw, 'direction'); did = visual_text(direction.get('id'), 'direction id')
        if did in direction_ids: raise OrchestrationError('duplicate direction id')
        direction_ids.add(did); visual_text(direction.get('summary'), 'direction summary')
        palette = visual_list(direction.get('palette'), 'palette')
        if any(not isinstance(x, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', x) for x in palette):
            raise OrchestrationError('palette colors must be #RRGGBB')
        uses = visual_list(direction.get('reference_ids'), 'direction references')
        if any(not isinstance(x, str) or x not in ids for x in uses): raise OrchestrationError('direction references an unknown source')
        boards.append(visual_file(root, direction.get('board')))
        if profile == 'motion-fx':
            motion = visual_list(direction.get('motion_reference_ids'), 'motion examples')
            if any(not isinstance(x, str) or x not in ids or not any(r['id'] == x and r.get('kind') == 'motion' for r in refs) for x in motion):
                raise OrchestrationError('motion directions require motion reference links')
    deliverables = visual_object(spec.get('deliverables'), 'deliverables')
    for key in ('editable', 'preview', 'report'):
        for value in visual_list(deliverables.get(key), f'{key} formats'): visual_text(value, 'format')
    required = spec.get('required_capabilities', [])
    if not isinstance(required, list) or any(not isinstance(x, str) or not x.strip() for x in required):
        raise OrchestrationError('required_capabilities must be a list of capability names')
    return boards


def cmd_visual(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db = load(root); t = get_task(db, a.id)
        if t.get('profile', 'code') not in VISUAL_PROFILES: raise OrchestrationError('visual task profile required')
        if a.cmd == 'visual-status':
            print(json.dumps({'profile': t['profile'], 'visual': t.get('visual'),
                              'evidence_mode': 'manual_declaration_not_tool_execution'}, ensure_ascii=True, indent=2)); return
        visual_text(a.actor, 'actor identity')
        if t['state'] in {'completed', 'integrated', 'interrupted'}: raise OrchestrationError('visual changes require an active or planned task; recover/reopen first')
        data = visual_json(a.file) if hasattr(a, 'file') else None
        if a.cmd in {'visual-spec', 'visual-preflight', 'visual-approve', 'visual-production'} and a.actor != t['created_by']:
            raise OrchestrationError('only the task director records visual contracts, preflight, approvals, and production')
        if a.cmd == 'visual-spec':
            if t['state'] not in {'planned', 'in_progress', 'blocked'}: raise OrchestrationError('visual spec changes require planned, in_progress, or blocked task')
            boards = validate_visual_spec(root, t['profile'], data)
            old = t.get('visual', {}); revision = old.get('revision', 0) + 1
            previous = old.get('spec', {})
            removed = set(previous.get('required_capabilities', [])) - set(data.get('required_capabilities', []))
            for role in ('editable', 'preview', 'report'):
                removed |= {role + ':' + value for value in set(previous.get('deliverables', {}).get(role, [])) - set(data['deliverables'][role])}
            if removed:
                reduction = visual_object(data.get('scope_reduction'), 'scope reduction for removed capabilities/formats')
                visual_source(reduction.get('approval'))
                declared_removed = visual_list(reduction.get('removed'), 'scope reduction removed items')
                for item in declared_removed: visual_text(item, 'scope reduction removed item')
                if sorted(declared_removed) != sorted(removed):
                    raise OrchestrationError('scope reduction must explicitly list every removed capability/role:format')
            v = {'revision': revision, 'spec': data, 'boards': boards, 'stage': 'directions',
                 'approvals': {}, 'events': old.get('events', []),
                 'spec_history': old.get('spec_history', []) + ([{'revision': old['revision'], 'spec': old['spec']}] if old else [])}
            t['visual'] = v
            visual_event(v, 'spec_recorded', a.reason)
        else:
            v = visual_current(root, t)
            if a.cmd == 'visual-preflight':
                capabilities = visual_object(data.get('capabilities'), 'capabilities')
                for name in VISUAL_CAPABILITIES | visual_required(t):
                    entry = visual_object(capabilities.get(name), f'capability {name}')
                    if entry.get('status') not in ('available', 'unavailable'): raise OrchestrationError('capability status must be available or unavailable')
                    visual_text(entry.get('evidence'), 'capability observed evidence')
                    if entry['status'] == 'available':
                        visual_text(entry.get('tool'), 'available capability tool'); visual_text(entry.get('source'), 'capability observation source')
                v['preflight'] = {'binding': visual_binding(t), 'capabilities': capabilities,
                                  'evidence_mode': 'manual_declaration_not_tool_execution'}
                v.pop('qa', None)
                visual_event(v, 'preflight_recorded', a.reason)
            elif a.cmd == 'visual-approve':
                visual_preflight(root, t); approval = dict(selection_source(t, data))
                if type(data.get('revision')) is not int or data['revision'] != v['revision']:
                    raise OrchestrationError('approval must explicitly name the current visual revision')
                if a.target == 'direction':
                    direction = next((d for d in v['spec']['directions'] if d['id'] == data.get('direction_id')), None)
                    if not direction or data.get('palette') != direction['palette']:
                        raise OrchestrationError('approval must explicitly select a current direction and exact palette')
                    if v.get('approvals', {}).get('direction'):
                        raise OrchestrationError('direction already approved; revise the spec for a direction/palette change')
                    v['stage'] = 'prototype'
                else:
                    visual_approval(root, t, 'direction')
                    if not v.get('prototype'): raise OrchestrationError('register a rendered prototype before approving it')
                    visual_files_current(root, v['prototype'])
                    if data.get('artifact_digest') != visual_digest(v['prototype']): raise OrchestrationError('approval must name the current prototype artifact_digest from visual-status')
                    approval['artifact_digest'] = visual_digest(v['prototype'])
                    approval['direction_digest'] = visual_digest(v['approvals']['direction'])
                approval.update({'binding': visual_binding(t), 'recorded_by': a.actor,
                                 'evidence_mode': 'manual_selection_record_not_authentication'})
                v['approvals'][a.target] = approval; v.pop('qa', None)
                visual_event(v, a.target + '_approved', a.reason)
            elif a.cmd == 'visual-artifacts':
                owner(t, a.actor)
                if t['state'] != 'in_progress': raise OrchestrationError('artifact registration requires an in_progress owner')
                visual_preflight(root, t); visual_approval(root, t, 'direction')
                if a.target == 'final': require_visual_production(root, t)
                elif v['stage'] != 'prototype': raise OrchestrationError('prototype changes require a revised spec before production')
                artifacts = [visual_file(root, item) for item in visual_list(data.get('artifacts'), 'artifacts')]
                if len({x['path'] for x in artifacts}) != len(artifacts): raise OrchestrationError('duplicate artifact paths')
                previews = [x for x in artifacts if x.get('role') == 'preview']
                if not previews: raise OrchestrationError('rendered preview required')
                for item in artifacts:
                    if item.get('role') not in ('editable', 'preview', 'report'): raise OrchestrationError('invalid artifact role')
                if t['profile'] == 'motion-fx':
                    for item in previews:
                        duration = item.get('duration_seconds')
                        if item.get('kind') != 'video' or item.get('format') not in ('mp4','webm','mov','gif') or Path(item['path']).suffix.lower() != '.' + item['format'] or type(duration) not in (int, float) or not (0 < duration < float('inf')):
                            raise OrchestrationError('motion preview needs a video format/path (mp4/webm/mov/gif) and finite positive duration_seconds; still frames are insufficient')
                if a.target == 'final':
                    for role, formats in v['spec']['deliverables'].items():
                        if role not in {'editable', 'preview', 'report'}: continue
                        if not set(formats).issubset({x['format'] for x in artifacts if x.get('role') == role}):
                            raise OrchestrationError(f'all promised {role} formats required')
                    v['artifacts'] = artifacts; v['stage'] = 'production'
                else:
                    v['prototype'] = artifacts; v['prototype_digest'] = visual_digest(artifacts)
                    v['approvals'].pop('prototype', None)
                v.pop('qa', None); visual_event(v, a.target + '_registered', a.reason)
            elif a.cmd == 'visual-production':
                if t['state'] != 'in_progress': raise OrchestrationError('production requires an in_progress owner')
                visual_preflight(root, t); visual_approval(root, t, 'direction'); visual_approval(root, t, 'prototype')
                if t.get('approval_mode'):
                    require_slice(t, v['approvals']['prototype'])
                if v['stage'] != 'prototype': raise OrchestrationError('production can only start after prototype approval')
                v['stage'] = 'production'; visual_event(v, 'production_started', a.reason)
            elif a.cmd == 'visual-qa':
                if t['state'] != 'ready_for_review': raise OrchestrationError('submit the final artifacts before visual QA')
                require_visual_production(root, t); visual_files_current(root, v.get('artifacts', []))
                qa = dict(data)
                visual_text(qa.get('reviewer'), 'QA reviewer identity')
                if qa.get('reviewer') != a.actor or a.actor in set(t.get('owner_history', [])) | {t['created_by']}:
                    raise OrchestrationError('visual reviewer must be independent of authors and director')
                if qa.get('result') not in ('pass', 'fail', 'inconclusive'): raise OrchestrationError('visual QA needs pass, fail, or inconclusive')
                visual_text(qa.get('findings'), 'QA findings')
                if qa['result'] == 'pass':
                    if qa.get('unrun') != []: raise OrchestrationError('visual PASS requires explicit empty unrun list')
                    opened = visual_list(qa.get('opened'), 'opened render evidence')
                    for preview in [x for x in v.get('artifacts', []) if x['role'] == 'preview']:
                        observation = next((x for x in opened if isinstance(x, dict) and x.get('path') == preview['path']), None)
                        if not observation or observation.get('content') != preview['content']:
                            raise OrchestrationError('QA must identify every current rendered preview and content fingerprint')
                        for key in ('tool', 'source', 'observation'): visual_text(observation.get(key), f'opened render {key}')
                        if t['profile'] == 'motion-fx':
                            if observation.get('mode') != 'playback' or type(observation.get('start_seconds')) not in (int, float) or observation['start_seconds'] != 0 or type(observation.get('end_seconds')) not in (int, float) or observation['end_seconds'] != preview['duration_seconds']:
                                raise OrchestrationError('motion QA requires full-duration temporal playback evidence; static frames are insufficient')
                    required = {'visual', 'palette', 'references', 'editable_source'}
                    if t['profile'] == 'ux-ui': required |= {'interactions', 'responsive', 'accessibility'}
                    if t['profile'] == 'storyboard': required |= {'sequence', 'continuity'}
                    if t['profile'] == 'motion-fx': required |= {'timing', 'transitions', 'continuity'}
                    checks = visual_object(qa.get('checks'), 'QA checks')
                    if not required.issubset(checks): raise OrchestrationError('missing required visual QA checks: ' + ', '.join(sorted(required-set(checks))))
                    for name, raw_check in checks.items():
                        check = visual_object(raw_check, f'QA {name}')
                        if check.get('result') != 'pass': raise OrchestrationError(f'visual QA check {name} is not passed')
                        for key in ('evidence', 'tool', 'source'): visual_text(check.get(key), f'QA {name} {key}')
                qa.update({'binding': visual_binding(t), 'artifact_digest': visual_digest(v.get('artifacts')),
                           'direction_digest': visual_digest(v['approvals']), 'owner_history_digest': owner_history_digest(t),
                           'attempt': t.get('attempt', 0), 'evidence_mode': 'manual_observation_record_not_tool_execution'})
                v['qa'] = qa; visual_event(v, 'qa_recorded', a.reason, result=qa['result'])
        log(db, t, a.cmd.replace('-', '_'), a.actor, revision=v['revision'], reason=a.reason)
        save(root, db)
        print(json.dumps({'revision': v['revision'], 'stage': v['stage'],
                          'prototype_digest': v.get('prototype_digest'),
                          'blockers': sorted(name for name in visual_required(t) if v.get('preflight', {}).get('capabilities', {}).get(name, {}).get('status') != 'available'),
                          'evidence_mode': 'manual_declaration_not_tool_execution'}))


def visual_statistics(db: dict[str, Any]) -> dict[str, Any]:
    # Export categories/counters only; user quotes, paths, sources and findings stay local.
    events = []; profiles = {}; counts = {}; reasons = {}; qa_results = {}
    allowed_events = {'spec_recorded','preflight_recorded','direction_approved','prototype_approved','prototype_registered','final_registered','production_started','qa_recorded','delivered'}
    for task in db['tasks'].values():
        if task.get('profile', 'code') not in VISUAL_PROFILES: continue
        profiles[task['profile']] = profiles.get(task['profile'], 0) + 1
        for event in task.get('visual', {}).get('events', []):
            if not isinstance(event,dict): raise OrchestrationError('invalid visual statistics event')
            def category(key, allowed):
                value=event.get(key)
                return value if isinstance(value,str) and value in allowed else None
            row={'task_ref': _ref(task['id'], 'orchestrator.stats.v1.task'),
                 'event':category('event',allowed_events),
                 'stage':category('stage',{'directions','prototype','production','qa','delivery'}),
                 'reason':category('reason',VISUAL_REASONS),
                 'result':category('result',{'pass','fail','inconclusive'}),
                 'revision':event.get('revision') if type(event.get('revision')) is int and event['revision']>0 else None}
            events.append(row)
            if row['event']: counts[row['event']]=counts.get(row['event'],0)+1
            if row['reason']: reasons[row['reason']]=reasons.get(row['reason'],0)+1
            if row['result']: qa_results[row['result']]=qa_results.get(row['result'],0)+1
    return {'evidence_source': 'manual_ledger_records', 'profiles': profiles, 'events': events,
            'summary': {'events_by_type': counts, 'revision_reasons': reasons, 'qa_results': qa_results},
            'observed_tokens': None, 'observed_model': None, 'observed_cost': None}


def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__ + ' Actor IDs and fresh-context/stop declarations are manual bookkeeping, not authentication or proof that an agent process stopped.')
    p.add_argument('--project',default='.',help='project directory (default: cwd)'); p.add_argument('--data-dir',help='bound project-contained ledger directory'); s=p.add_subparsers(dest='cmd',required=True)
    q=s.add_parser('bind-storage'); q.add_argument('--data-dir',required=True,help='project-contained ledger directory to bind explicitly')
    q=s.add_parser('init'); q.add_argument('--max-workers',type=int,default=3); q.add_argument('--review-round-limit',type=int,default=2); q.add_argument('--consultation-limit',type=int,default=1); q.add_argument('--escalation-limit',type=int,default=1)
    q=s.add_parser('add'); q.add_argument('id'); q.add_argument('--goal',required=True); q.add_argument('--depends-on',default=''); q.add_argument('--priority',type=int,default=50); q.add_argument('--risk',choices=['low','medium','high','critical'],default='medium'); q.add_argument('--scope',required=True,help='comma-separated paths/resources; * means shared'); q.add_argument('--acceptance',required=True); q.add_argument('--actor',required=True)
    q.add_argument('--review-mode',choices=['planned','manual-control'],default='planned',help='manual-control is an explicit low-risk opt-out from the acceptance-plan gate')
    q.add_argument('--readiness',help='compact readiness JSON contract'); q.add_argument('--approval-mode',choices=['observed','explicit-user'],default='observed')
    q.add_argument('--profile', choices=['code', *sorted(VISUAL_PROFILES)], default='code')
    s.add_parser('list')
    q=s.add_parser('plan-review'); q.add_argument('id'); q.add_argument('--actor',required=True,help='manual actor ID; not authentication'); q.add_argument('--director',required=True); q.add_argument('--reviewer',required=True); q.add_argument('--reviewer-role',choices=sorted(ROLE_DEFAULTS)); q.add_argument('--contract-version',required=True); q.add_argument('--scenario',action='append',required=True); q.add_argument('--fresh-context-attested',action='store_true',help='manual declaration, not authentication; requires all four context items'); q.add_argument('--context-item',action='append',default=[],choices=sorted(PLAN_CONTEXT_ITEMS),help='manual fresh-context checklist item, not proof of a new reviewer context')
    q=s.add_parser('assign'); q.add_argument('id'); q.add_argument('--owner',required=True); q.add_argument('--actor',required=True); q.add_argument('--owner-role',choices=sorted(ROLE_DEFAULTS))
    for cmd in ('start','interrupt','submit'):
        q=s.add_parser(cmd); q.add_argument('id'); q.add_argument('--actor',required=True)
    q=s.add_parser('recover',help='reassign an interrupted task after declaring the prior owner stopped'); q.add_argument('id'); q.add_argument('--owner',required=True,help='manual identity for the new owner'); q.add_argument('--actor',required=True,help='manual actor ID; identities are not authentication'); q.add_argument('--context',required=True); q.add_argument('--old-agent-interrupted',action='store_true',help='declare that the prior owner stopped; not proof that its process was killed'); q.add_argument('--owner-role',choices=sorted(ROLE_DEFAULTS))
    q=s.add_parser('replan'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--director',required=True); q.add_argument('--reason',required=True); q.add_argument('--goal'); q.add_argument('--scope'); q.add_argument('--acceptance'); q.add_argument('--diagnosis'); q.add_argument('--changed-approach')
    q=s.add_parser('escalate'); q.add_argument('id'); q.add_argument('--actor',required=True,help='manual actor ID; not authentication'); q.add_argument('--director',required=True); q.add_argument('--owner',required=True,help='manual instance identity'); q.add_argument('--owner-role',choices=['sol_senior'],required=True); q.add_argument('--reason',required=True); q.add_argument('--context',required=True); q.add_argument('--old-agent-interrupted',action='store_true',help='declare that the previous owner stopped; not proof that its process was killed')
    q=s.add_parser('consult'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--director',required=True); q.add_argument('--consultant',required=True,help='manual instance identity, separate from canonical role'); q.add_argument('--consultant-role',choices=['astra_consultant'],required=True); q.add_argument('--question',required=True); q.add_argument('--budget',required=True); q.add_argument('--outcome',required=True)
    q=s.add_parser('review'); q.add_argument('id'); q.add_argument('--reviewer',required=True,help='manual reviewer ID; not authentication'); q.add_argument('--reviewer-role',choices=sorted(ROLE_DEFAULTS)); q.add_argument('--result',choices=['pass','fail','inconclusive'],required=True); q.add_argument('--check',action='append',default=[],help='PASS; command=...; result=exit 0|passed; evidence=...'); q.add_argument('--unrun',action='append',default=[]); q.add_argument('--findings',required=True); q.add_argument('--fresh-context-attested',action='store_true',help='manual declaration, not authentication; requires all four context items'); q.add_argument('--context-item',action='append',default=[],choices=sorted(PLAN_CONTEXT_ITEMS),help='manual fresh-context checklist item, not proof of a new reviewer context'); q.add_argument('--senior-verified',action='store_true'); q.add_argument('--senior-reviewer',help='manual identity of independent read-only Sol reviewer'); q.add_argument('--senior-role',choices=['sol_reviewer']); q.add_argument('--astra-consulted',action='store_true'); q.add_argument('--director-resolved',action='store_true'); q.add_argument('--director-decision',default='')
    q.add_argument('--readiness-evidence'); q.add_argument('--defects',help='JSON list of unified defect records')
    q=s.add_parser('passport'); q.add_argument('id')
    q=s.add_parser('integrate'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--check',action='append',default=[]); q.add_argument('--senior-verified',action='store_true'); q.add_argument('--senior-reviewer',help='manual identity of independent read-only Sol reviewer'); q.add_argument('--senior-role',choices=['sol_reviewer']); q.add_argument('--astra-consulted',action='store_true'); q.add_argument('--director-resolved',action='store_true'); q.add_argument('--director-decision',default='')
    q=s.add_parser('complete'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--check',action='append',default=[])
    q=s.add_parser('snapshot'); q.add_argument('--json',action='store_true')
    q=s.add_parser('stats',help='export privacy-filtered ledger statistics'); q.add_argument('--format',choices=['json','csv'],default='json')
    for cmd in ('visual-spec','visual-preflight','visual-approve','visual-artifacts','visual-production','visual-qa','visual-status'):
        q=s.add_parser(cmd,help='record visual workflow evidence; does not execute tools or authenticate identities')
        q.add_argument('id')
        if cmd != 'visual-status':
            q.add_argument('--actor',required=True)
            q.add_argument('--reason',choices=sorted(VISUAL_REASONS),default='initial')
        if cmd not in {'visual-production','visual-status'}: q.add_argument('--file',required=True,help='structured JSON evidence file')
        if cmd == 'visual-approve': q.add_argument('--target',choices=['direction','prototype'],required=True)
        if cmd == 'visual-artifacts': q.add_argument('--target',choices=['prototype','final'],required=True)
    return p

def main(argv: Optional[list[str]]=None) -> int:
    a=parser().parse_args(argv)
    try:
        root=project_root(Path(a.project).resolve())
        if a.cmd=='bind-storage': cmd_bind(a,root); return 0
        selected_dir(root,a.data_dir)
        if a.cmd=='init':
            if min(a.max_workers,a.review_round_limit,a.consultation_limit,a.escalation_limit)<1: raise OrchestrationError('limits must be positive')
            cmd_init(a,root)
        elif a.cmd=='snapshot':
            snap=snapshot(root); print(json.dumps(snap,ensure_ascii=True) if a.json else f"{snap['fingerprint']}\tHEAD={snap['head']}\tchanged={','.join(snap['paths']) or '(clean)'}")
        elif a.cmd=='stats': cmd_stats(a,root)
        elif a.cmd=='passport': print(json.dumps(result_passport(get_task(load(root),a.id),snapshot(root)),ensure_ascii=True,indent=2))
        elif a.cmd.startswith('visual-'): cmd_visual(a,root)
        elif a.cmd=='add': cmd_add(a,root)
        elif a.cmd=='list': cmd_list(a,root)
        elif a.cmd=='plan-review': cmd_plan_review(a,root)
        elif a.cmd=='assign': cmd_assign(a,root)
        elif a.cmd=='start': cmd_state(a,root,'in_progress')
        elif a.cmd=='interrupt': cmd_state(a,root,'interrupted')
        elif a.cmd=='submit': cmd_state(a,root,'ready_for_review')
        elif a.cmd=='recover': cmd_recover(a,root)
        elif a.cmd=='replan': cmd_replan(a,root)
        elif a.cmd=='escalate': cmd_escalate(a,root)
        elif a.cmd=='consult': cmd_consult(a,root)
        elif a.cmd=='review': cmd_review(a,root)
        elif a.cmd=='integrate': cmd_integrate(a,root)
        elif a.cmd=='complete': cmd_complete(a,root)
        return 0
    except OrchestrationError as e:
        print(f'orchestrate: {e}',file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
