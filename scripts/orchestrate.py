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
    'review_fail': {('ready_for_review','in_progress')},
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
    return {'schema':1,'coverage':stats['coverage'],'clock_source':'system_wall_clock_utc','events':events,'summary':{'event_count':len(events),'task_count':len(attempts),'events_by_type':bytype,'events_by_role':byrole,'attempts_by_task':attempts}}

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
        if a.review_mode == 'manual-control' and a.risk != 'low': raise OrchestrationError('manual review control opt-out is limited to low-risk tasks')
        task={'id':a.id,'goal':a.goal,'depends_on':deps,'priority':a.priority,'risk':a.risk,'scope':normalize_scope(a.scope,root), 'acceptance':a.acceptance,'contract_revision':1,'review_mode':a.review_mode,'acceptance_plans':[],'owner':None,'owner_history':[],'attempt':0,'state':'planned','review_rounds':0,'consultations':0,'evidence':[],'snapshot':None,'created_by':a.actor,'created_at':time.time()}
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
        prior=t['state']; transition(t,target)
        if target == 'in_progress':
            t['attempt'] = int(t.get('attempt', 0)) + 1
            t.pop('review_snapshot', None)
        log(db,t,target,a.actor,attempt=t.get('attempt'),owner_role=t.get('owner_role'),_stats_from_state=prior); save(root,db)

def cmd_replan(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if a.actor != a.director: raise OrchestrationError('only the director may re-plan a task')
        if t['state'] not in {'planned', 'blocked'}:
            raise OrchestrationError('replan requires planned or blocked state with no active worker reservation; interrupt and recover a running worker first')
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
        if a.reviewer in set(t.get('owner_history', [t['owner']])): raise OrchestrationError('reviewer must be distinct from every task author')
        if t['review_rounds']>=db['config']['review_round_limit'] + t.get('escalations',0): raise OrchestrationError('review round allowance reached; director must re-evaluate or create a follow-up task')
        if a.result == 'pass' and (not a.check or any(not check_passed(c) for c in a.check)):
            raise OrchestrationError('pass requires each --check as PASS; command=...; result=exit 0|passed; evidence=...')
        senior_evidence=senior_role_evidence(a, t)
        astra_resolution=astra_resolution_evidence(a,t)
        review_from_state=t['state']; review_snapshot=snapshot(root)
        evidence={'reviewer':a.reviewer,'result':a.result,'checks':a.check,'unrun':a.unrun,'findings':a.findings,'senior_verifier':senior_evidence,'astra_resolution':astra_resolution,'fresh_context':{'attested':True,'items':sorted(set(a.context_item)),'identity_is_manual_attestation':True},'contract_revision':t.get('contract_revision',1),'attempt':t.get('attempt',0),'owner_history_digest':owner_history_digest(t),'time':time.time(),'snapshot':review_snapshot}
        t['review_rounds']+=1; t['evidence'].append(evidence); t['review_snapshot']=review_snapshot
        if a.result=='pass':
            if t['risk'] in {'high','critical'} and not (a.senior_verified or astra_resolution): raise OrchestrationError('high risk needs canonical read-only Sol reviewer verification or recorded canonical Astra consultation with director resolution')
        else:
            target='in_progress' if a.result=='fail' else 'blocked'
            transition(t,target)
        log(db,t,'review_'+a.result,a.reviewer,checks=a.check,unrun=a.unrun,findings=a.findings,reviewer_role=a.reviewer_role,reviewer=a.reviewer,_stats_from_state=review_from_state); save(root,db)

def cmd_integrate(a: argparse.Namespace, root: Path) -> None:
    with locked(root):
        db=load(root); t=get_task(db,a.id)
        if t['state']!='ready_for_review' or not current_review(t): raise OrchestrationError('current passing review evidence required before integration')
        require_acceptance_plan(t)
        reviewer=t['evidence'][-1]['reviewer']
        if reviewer in set(t.get('owner_history', [])):
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
        if not t.get('evidence') or not current_review(t): raise OrchestrationError('current passing review evidence is required at completion')
        if t['evidence'][-1]['reviewer'] in set(t.get('owner_history', [])):
            raise OrchestrationError('recorded reviewer is no longer independent of every task author')
        if snapshot(root)!=t['integrated_snapshot']: raise OrchestrationError('integrated snapshot is stale; completion refused')
        if not a.check or any(not check_passed(c) for c in a.check): raise OrchestrationError('completion verification requires --check formatted PASS; command=...; result=exit 0|passed; evidence=...')
        prior=t['state']; t['state']='completed'; log(db,t,'completed',a.actor,checks=a.check,_stats_from_state=prior); save(root,db)

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

def parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(description=__doc__ + ' Actor IDs and fresh-context/stop declarations are manual bookkeeping, not authentication or proof that an agent process stopped.')
    p.add_argument('--project',default='.',help='project directory (default: cwd)'); p.add_argument('--data-dir',help='bound project-contained ledger directory'); s=p.add_subparsers(dest='cmd',required=True)
    q=s.add_parser('bind-storage'); q.add_argument('--data-dir',required=True,help='project-contained ledger directory to bind explicitly')
    q=s.add_parser('init'); q.add_argument('--max-workers',type=int,default=3); q.add_argument('--review-round-limit',type=int,default=2); q.add_argument('--consultation-limit',type=int,default=1); q.add_argument('--escalation-limit',type=int,default=1)
    q=s.add_parser('add'); q.add_argument('id'); q.add_argument('--goal',required=True); q.add_argument('--depends-on',default=''); q.add_argument('--priority',type=int,default=50); q.add_argument('--risk',choices=['low','medium','high','critical'],default='medium'); q.add_argument('--scope',required=True,help='comma-separated paths/resources; * means shared'); q.add_argument('--acceptance',required=True); q.add_argument('--actor',required=True)
    q.add_argument('--review-mode',choices=['planned','manual-control'],default='planned',help='manual-control is an explicit low-risk opt-out from the acceptance-plan gate')
    s.add_parser('list')
    q=s.add_parser('plan-review'); q.add_argument('id'); q.add_argument('--actor',required=True,help='manual actor ID; not authentication'); q.add_argument('--director',required=True); q.add_argument('--reviewer',required=True); q.add_argument('--reviewer-role',choices=sorted(ROLE_DEFAULTS)); q.add_argument('--contract-version',required=True); q.add_argument('--scenario',action='append',required=True); q.add_argument('--fresh-context-attested',action='store_true',help='manual declaration, not authentication; requires all four context items'); q.add_argument('--context-item',action='append',default=[],choices=sorted(PLAN_CONTEXT_ITEMS),help='manual fresh-context checklist item, not proof of a new reviewer context')
    q=s.add_parser('assign'); q.add_argument('id'); q.add_argument('--owner',required=True); q.add_argument('--actor',required=True); q.add_argument('--owner-role',choices=sorted(ROLE_DEFAULTS))
    for cmd in ('start','interrupt','submit'):
        q=s.add_parser(cmd); q.add_argument('id'); q.add_argument('--actor',required=True)
    q=s.add_parser('recover',help='reassign an interrupted task after declaring the prior owner stopped'); q.add_argument('id'); q.add_argument('--owner',required=True,help='manual identity for the new owner'); q.add_argument('--actor',required=True,help='manual actor ID; identities are not authentication'); q.add_argument('--context',required=True); q.add_argument('--old-agent-interrupted',action='store_true',help='declare that the prior owner stopped; not proof that its process was killed'); q.add_argument('--owner-role',choices=sorted(ROLE_DEFAULTS))
    q=s.add_parser('replan'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--director',required=True); q.add_argument('--reason',required=True); q.add_argument('--goal'); q.add_argument('--scope'); q.add_argument('--acceptance')
    q=s.add_parser('escalate'); q.add_argument('id'); q.add_argument('--actor',required=True,help='manual actor ID; not authentication'); q.add_argument('--director',required=True); q.add_argument('--owner',required=True,help='manual instance identity'); q.add_argument('--owner-role',choices=['sol_senior'],required=True); q.add_argument('--reason',required=True); q.add_argument('--context',required=True); q.add_argument('--old-agent-interrupted',action='store_true',help='declare that the previous owner stopped; not proof that its process was killed')
    q=s.add_parser('consult'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--director',required=True); q.add_argument('--consultant',required=True,help='manual instance identity, separate from canonical role'); q.add_argument('--consultant-role',choices=['astra_consultant'],required=True); q.add_argument('--question',required=True); q.add_argument('--budget',required=True); q.add_argument('--outcome',required=True)
    q=s.add_parser('review'); q.add_argument('id'); q.add_argument('--reviewer',required=True,help='manual reviewer ID; not authentication'); q.add_argument('--reviewer-role',choices=sorted(ROLE_DEFAULTS)); q.add_argument('--result',choices=['pass','fail','inconclusive'],required=True); q.add_argument('--check',action='append',default=[],help='PASS; command=...; result=exit 0|passed; evidence=...'); q.add_argument('--unrun',action='append',default=[]); q.add_argument('--findings',required=True); q.add_argument('--fresh-context-attested',action='store_true',help='manual declaration, not authentication; requires all four context items'); q.add_argument('--context-item',action='append',default=[],choices=sorted(PLAN_CONTEXT_ITEMS),help='manual fresh-context checklist item, not proof of a new reviewer context'); q.add_argument('--senior-verified',action='store_true'); q.add_argument('--senior-reviewer',help='manual identity of independent read-only Sol reviewer'); q.add_argument('--senior-role',choices=['sol_reviewer']); q.add_argument('--astra-consulted',action='store_true'); q.add_argument('--director-resolved',action='store_true'); q.add_argument('--director-decision',default='')
    q=s.add_parser('integrate'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--check',action='append',default=[]); q.add_argument('--senior-verified',action='store_true'); q.add_argument('--senior-reviewer',help='manual identity of independent read-only Sol reviewer'); q.add_argument('--senior-role',choices=['sol_reviewer']); q.add_argument('--astra-consulted',action='store_true'); q.add_argument('--director-resolved',action='store_true'); q.add_argument('--director-decision',default='')
    q=s.add_parser('complete'); q.add_argument('id'); q.add_argument('--actor',required=True); q.add_argument('--check',action='append',default=[])
    q=s.add_parser('snapshot'); q.add_argument('--json',action='store_true')
    q=s.add_parser('stats',help='export privacy-filtered ledger statistics'); q.add_argument('--format',choices=['json','csv'],default='json')
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
