#!/usr/bin/env python3
"""Install the native Codex multi-agent orchestrator skill and optional hooks.

Cross-platform, standard library only. The installer is deliberately boring:

  * it plans every write before touching disk,
  * it never overwrites a differing file unless you pass --force,
  * it never overwrites PROJECT_STATE.md or AGENTS.md at all,
  * it never edits config.toml, user-level hooks.json, credentials, or routing,
  * it never reaches the network.

Exit codes:
    0  success (including a clean dry run)
    2  usage or environment problem
    3  conflicts detected and nothing was written

Examples:
    python scripts/install.py --project /path/to/repo --codex-home ~/.codex
    python scripts/install.py --project /path/to/repo --codex-home ~/.codex --hooks
    CODEX_HOME=~/.codex python scripts/install.py --project /path/to/repo --dry-run
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import shlex
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "sol-deepseek-project-orchestrator"
AGENT_FILES = (
    "luna-worker.toml",
    "luna-reviewer.toml",
    "sol-senior.toml",
    "sol-reviewer.toml",
    "astra-consultant.toml",
    "luna-state-editor.toml",
)
MANIFEST_NAME = "orchestrator-install-manifest.json"
ROOT_PROFILE_NAME = "orchestrator-director.config.toml"
REGISTRY_NAME = ".orchestrator-install-registry.json"
LOCK_NAME = ".orchestrator-install.lock"

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_CONFLICT = 3

CREATE = "create"
UPDATE = "update"
UNCHANGED = "unchanged"
PRESERVE = "preserve"
CONFLICT = "conflict"
REMOVE = "remove"

MANAGED = "managed"
USER_OWNED = "user-owned"
FORCE_PROTECTED = "force-protected"


class InstallError(Exception):
    """A usage or environment problem that must stop the install."""


@dataclass
class PlanItem:
    action: str
    path: Path
    origin: str
    kind: str = MANAGED
    source: Optional[Path] = None
    content: Optional[bytes] = None
    note: str = ""
    expected_hash: Optional[str] = None

    def display_path(self) -> str:
        return str(self.path)


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, item: PlanItem) -> None:
        self.items.append(item)

    def conflicts(self) -> list[PlanItem]:
        return [item for item in self.items if item.action == CONFLICT]

    def blocked_conflicts(self, force: bool) -> list[PlanItem]:
        return [
            item for item in self.conflicts()
            if not force or item.kind == FORCE_PROTECTED
        ]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def read_source(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InstallError(f"cannot read bundled file {path}: {exc}") from exc


def read_existing(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return None
    except OSError:
        return None


def classify_managed(dest: Path, content: bytes) -> str:
    if dest.exists() and not dest.is_file():
        return CONFLICT
    existing = read_existing(dest)
    if existing is None:
        return CREATE
    if existing == content:
        return UNCHANGED
    return CONFLICT


def classify_user_owned(dest: Path) -> str:
    return PRESERVE if dest.exists() else CREATE


def add_file_plan(
    plan: Plan,
    source: Path,
    dest: Path,
    origin: str,
    kind: str = MANAGED,
    roots: Optional[tuple[Path, ...]] = None,
) -> None:
    if roots is not None:
        validate_destination(dest, roots)
    content = read_source(source)
    action = (
        classify_user_owned(dest)
        if kind == USER_OWNED
        else classify_managed(dest, content)
    )
    note = ""
    if action == PRESERVE:
        note = "existing file kept"
    plan.add(
        PlanItem(
            action=action,
            path=dest,
            origin=origin,
            kind=kind,
            source=source,
            content=content,
            note=note,
            expected_hash=(hashlib.sha256(read_existing(dest)).hexdigest() if action == CONFLICT and read_existing(dest) is not None else None),
        )
    )


def add_generated_plan(
    plan: Plan,
    dest: Path,
    origin: str,
    content: bytes,
    kind: str = MANAGED,
    roots: Optional[tuple[Path, ...]] = None,
) -> None:
    if roots is not None:
        validate_destination(dest, roots)
    action = (
        classify_user_owned(dest)
        if kind == USER_OWNED
        else classify_managed(dest, content)
    )
    plan.add(
        PlanItem(
            action=action,
            path=dest,
            origin=origin,
            kind=kind,
            source=None,
            content=content,
            expected_hash=(hashlib.sha256(read_existing(dest)).hexdigest() if action == CONFLICT and read_existing(dest) is not None else None),
        )
    )


def is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def validate_destination(path: Path, roots: tuple[Path, ...]) -> None:
    """Require a destination and every existing ancestor to stay in a chosen root."""
    absolute = Path(os.path.abspath(path))
    root = next((candidate for candidate in roots if absolute == candidate or candidate in absolute.parents), None)
    if root is None:
        raise InstallError(f"destination escapes the selected project and Codex home: {path}")
    current = root
    if is_reparse_point(current):
        raise InstallError(f"selected destination root is a reparse point: {current}")
    relative = absolute.relative_to(root)
    for part in relative.parts:
        current = current / part
        if is_reparse_point(current):
            raise InstallError(f"destination traverses a symlink or junction: {current}")


@contextlib.contextmanager
def installation_lock(codex_home: Path):
    """Acquire a nonblocking process lock; OS releases it after crashes."""
    codex_home.mkdir(parents=True, exist_ok=True)
    lock_path = codex_home / LOCK_NAME
    if is_reparse_point(codex_home) or is_reparse_point(lock_path):
        raise InstallError("Codex home or installer lock is a symlink/junction")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(str(lock_path), flags, 0o600)
    except OSError as exc:
        raise InstallError(f"cannot open installer lock {lock_path}: {exc}") from exc
    stream = os.fdopen(descriptor, "r+b", buffering=0)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise InstallError("another install/uninstall is active for this Codex home") from exc
            locked = True
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise InstallError("another install/uninstall is active for this Codex home") from exc
            locked = True
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
        else:
            stream.close()


def owned_install_paths(project: Path, codex_home: Path) -> set[Path]:
    """Enumerate exact file paths this installer may own, never broad folders."""
    skill_dir = codex_home / "skills" / SKILL_NAME
    paths = {
        skill_dir / source.relative_to(REPO_ROOT / "skill")
        for source in iter_source_tree(REPO_ROOT / "skill")
    }
    paths.add(skill_dir / "ARCHITECTURE.md")
    paths.add(skill_dir / "scripts" / "orchestrate.py")
    paths.update(codex_home / "agents" / name for name in AGENT_FILES)
    paths.add(codex_home / ROOT_PROFILE_NAME)
    hooks_dir = project / ".codex" / "hooks"
    paths.update(
        hooks_dir / source.name
        for source in iter_source_tree(REPO_ROOT / "hooks")
        if source.suffix == ".py"
    )
    paths.add(hooks_dir / "orchestrate.py")
    paths.add(project / ".codex" / "hooks.json")
    return paths


def read_valid_manifest(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("files"), dict):
            return None
        unsigned = {key: value for key, value in data.items() if key != "manifest_sha256"}
        digest = hashlib.sha256(
            json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        if data.get("manifest_sha256") != digest:
            return None
        if any(not isinstance(name, str) or not isinstance(value, str) for name, value in data["files"].items()):
            return None
        return data
    except (OSError, ValueError, AttributeError):
        return None


def validated_managed_records(
    manifest: Optional[dict], project: Path, codex_home: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Bound manifest claims to exact managed paths; a checksum is not authorship.

    Modified files retain their original digest so uninstall can preserve them.
    Destructive callers must additionally compare the current bytes to that digest.
    Unknown obsolete paths are preserved rather than inferred from a directory.
    """
    roots = (project.resolve(), codex_home.resolve())
    allowed = {str(Path(os.path.abspath(path))) for path in owned_install_paths(project, codex_home)}
    accepted: dict[str, str] = {}
    rejected: dict[str, str] = {}
    for raw_path, digest in (manifest or {}).get("files", {}).items():
        candidate = Path(raw_path)
        if not candidate.is_absolute() or str(Path(os.path.abspath(candidate))) != raw_path or raw_path not in allowed:
            rejected[raw_path] = "path is outside the installer's exact managed-file allowlist"
            continue
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            rejected[raw_path] = "invalid recorded SHA-256 digest"
            continue
        try:
            validate_destination(candidate, roots)
        except InstallError:
            rejected[raw_path] = "path traverses outside a selected root or a reparse point"
            continue
        accepted[raw_path] = digest
    return accepted, rejected


def is_shared_path(path: Path, codex_home: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    home = Path(os.path.abspath(codex_home))
    return absolute == home or home in absolute.parents


def read_registry(codex_home: Path) -> dict:
    path = codex_home / REGISTRY_NAME
    if not path.exists():
        return {"version": 1, "files": {}}
    if is_reparse_point(path):
        raise InstallError(f"installer registry is a symlink/junction: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstallError(f"cannot read installer registry {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("files"), dict):
        raise InstallError(f"installer registry is invalid: {path}")
    allowed = set()
    skill_dir = codex_home / "skills" / SKILL_NAME
    allowed.update(skill_dir / source.relative_to(REPO_ROOT / "skill") for source in iter_source_tree(REPO_ROOT / "skill"))
    allowed.update({skill_dir / "ARCHITECTURE.md", skill_dir / "scripts" / "orchestrate.py", codex_home / ROOT_PROFILE_NAME})
    allowed.update(codex_home / "agents" / name for name in AGENT_FILES)
    clean = {}
    for raw, record in data["files"].items():
        path = Path(raw)
        if not path.is_absolute() or Path(os.path.abspath(path)) not in allowed:
            raise InstallError(f"registry path is outside the exact shared-file allowlist: {raw}")
        if not isinstance(record, dict):
            raise InstallError(f"invalid registry record for {raw}")
        digest, owners = record.get("sha256"), record.get("owners")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise InstallError(f"invalid registry hash for {raw}")
        if not isinstance(owners, list) or not owners or any(not isinstance(owner, str) or not Path(owner).is_absolute() for owner in owners):
            raise InstallError(f"invalid registry owners for {raw}")
        clean[raw] = {"sha256": digest, "owners": sorted(set(owners))}
    return {"version": 1, "files": clean}


def write_json_atomic(path: Path, value: dict, roots: tuple[Path, ...]) -> None:
    validate_destination(path, roots)
    content = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        old = path.read_bytes()
    except FileNotFoundError:
        old = None
    atomic_write(path, content, backup=False, roots=roots, no_clobber=old is None,
                 expected_hash=hashlib.sha256(old).hexdigest() if old is not None else None)


def write_manifest(project: Path, codex_home: Path, files: dict[str, str]) -> None:
    value = {"version": 1, "files": files}
    value["manifest_sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    write_json_atomic(project / ".codex" / MANIFEST_NAME, value, (project.resolve(), codex_home.resolve()))


def set_registry_owner(registry: dict, raw_path: str, digest: str, project: Path) -> None:
    record = registry["files"].setdefault(raw_path, {"sha256": digest, "owners": []})
    record["sha256"] = digest
    if str(project) not in record["owners"]:
        record["owners"].append(str(project))
    record["owners"].sort()


def drop_registry_owner(registry: dict, raw_path: str, project: Path) -> None:
    record = registry["files"].get(raw_path)
    if not record:
        return
    record["owners"] = [owner for owner in record["owners"] if owner != str(project)]
    if not record["owners"]:
        registry["files"].pop(raw_path, None)



# ---------------------------------------------------------------------------
# Hook configuration
# ---------------------------------------------------------------------------


def posix_interpreter() -> str:
    if os.name != "nt":
        found = shutil.which("python3") or shutil.which("python")
        if found:
            return found
    return "python3"


def windows_interpreter() -> Optional[str]:
    if os.name != "nt":
        return None
    if sys.executable:
        return sys.executable
    return shutil.which("python") or shutil.which("py")


def hook_command(script: Path, use_windows: bool, data_dir: Optional[str] = None) -> Optional[str]:
    if use_windows:
        interpreter = windows_interpreter()
        if not interpreter:
            return None
        # Paths are data in an encoded script, not cmd.exe metacharacters.
        def ps_literal(value: str) -> str:
            return "'" + value.replace("'", "''") + "'"
        extra = f" --data-dir {ps_literal(data_dir)}" if data_dir else ""
        source = f"& {ps_literal(interpreter)} {ps_literal(str(script))}{extra}; exit $LASTEXITCODE"
        encoded = base64.b64encode(source.encode("utf-16le")).decode("ascii")
        return f"powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand {encoded}"
    extra = f" --data-dir {shlex.quote(data_dir)}" if data_dir else ""
    return f"{shlex.quote(posix_interpreter())} {shlex.quote(str(script))}{extra}"


def build_hooks_config(hooks_dir: Path, data_dir: Optional[str] = None) -> bytes:
    inject = hooks_dir / "inject_project_state.py"
    stop = hooks_dir / "stop_project_state_check.py"

    def handler(script: Path, status: str, extra: Optional[dict] = None) -> dict:
        handler_dict: dict = {
            "type": "command",
            "command": hook_command(script, use_windows=False, data_dir=data_dir),
        }
        windows = hook_command(script, use_windows=True, data_dir=data_dir)
        if windows:
            # In hooks.json the key is camelCase; only TOML accepts
            # command_windows. See the Codex hooks documentation, "Notes".
            handler_dict["commandWindows"] = windows
        handler_dict["timeout"] = 20 if script is stop else 15
        handler_dict["statusMessage"] = status
        if extra:
            handler_dict.update(extra)
        return handler_dict

    config = {
        "_generated": (
            "Generated by sol-deepseek-project-orchestrator scripts/install.py. "
            "Re-run the installer with --hooks --force after moving this "
            "repository, because the commands below contain absolute paths."
        ),
            "description": (
            "Project state injection and one-shot state nudge for the "
            "native Codex orchestrator workflow."
        ),
        "hooks": {
            # SessionStart with source "compact" is what covers the window
            # after compaction: Codex runs matching SessionStart hooks before
            # the next model request, including mid-turn automatic compaction.
            # PostCompact only supports the common output fields, so it cannot
            # carry additionalContext.
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        handler(
                            inject,
                            "Loading project state",
                            {"additionalContextLimit": 4000},
                        )
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [handler(stop, "Checking project state")],
                }
            ],
        },
    }
    text = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def iter_source_tree(root: Path) -> list[Path]:
    if not root.is_dir():
        raise InstallError(f"bundled directory missing: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files.append(path)
    return files


def build_plan(
    project: Path,
    codex_home: Path,
    *,
    with_hooks: bool,
    data_dir: Optional[str] = None,
    with_agents_md: bool,
    with_agent: bool,
    prune: bool,
    plan: Plan,
) -> Plan:
    roots = (project.resolve(), codex_home.resolve())
    manifest_path = project / ".codex" / MANIFEST_NAME
    for destination in owned_install_paths(project, codex_home):
        validate_destination(destination, roots)
    validate_destination(manifest_path, roots)
    skill_dir = REPO_ROOT / "skill"
    skill_dest = codex_home / "skills" / SKILL_NAME

    for source in iter_source_tree(skill_dir):
        relative = source.relative_to(skill_dir)
        add_file_plan(
            plan,
            source,
            skill_dest / relative,
            origin="skill",
            roots=roots,
        )

    architecture = REPO_ROOT / "ARCHITECTURE.md"
    if architecture.is_file():
        add_file_plan(
            plan,
            architecture,
            skill_dest / "ARCHITECTURE.md",
            origin="skill-doc",
            roots=roots,
        )
    else:
        plan.warnings.append(
            "ARCHITECTURE.md is missing from the bundle; installed skill will "
            "not carry the long-form design document."
        )

    add_file_plan(
        plan,
        REPO_ROOT / "templates" / ROOT_PROFILE_NAME,
        codex_home / ROOT_PROFILE_NAME,
        origin="root-profile",
        roots=roots,
    )

    if with_agent:
        for agent_name in AGENT_FILES:
            add_file_plan(
                plan,
                REPO_ROOT / "templates" / "agents" / agent_name,
                codex_home / "agents" / agent_name,
                origin="agent",
                roots=roots,
            )

    # The runtime CLI is distributed inside the skill so it works after the
    # source checkout is moved or removed.
    runtime = REPO_ROOT / "scripts" / "orchestrate.py"
    if not runtime.is_file():
        raise InstallError(f"required bundled runtime missing: {runtime}")
    add_file_plan(
        plan,
        runtime,
        skill_dest / "scripts" / "orchestrate.py",
        origin="runtime",
        roots=roots,
    )

    add_file_plan(
        plan,
        REPO_ROOT / "templates" / "PROJECT_STATE.md",
        project / ".codex" / "PROJECT_STATE.md",
        origin="state-template",
        kind=USER_OWNED,
        roots=roots,
    )

    if with_agents_md:
        add_file_plan(
            plan,
            REPO_ROOT / "templates" / "AGENTS.md",
            project / "AGENTS.md",
            origin="agents-template",
            kind=USER_OWNED,
            roots=roots,
        )

    if with_hooks:
        hooks_dest_dir = project / ".codex" / "hooks"
        for source in iter_source_tree(REPO_ROOT / "hooks"):
            if source.suffix != ".py":
                continue
            add_file_plan(
                plan,
                source,
                hooks_dest_dir / source.name,
                origin="hooks",
                roots=roots,
            )
        add_file_plan(
            plan,
            runtime,
            hooks_dest_dir / "orchestrate.py",
            origin="hooks-runtime",
            roots=roots,
        )
        add_generated_plan(
            plan,
            project / ".codex" / "hooks.json",
            origin="hooks-config",
            content=build_hooks_config(hooks_dest_dir, data_dir=data_dir),
            kind=FORCE_PROTECTED,
            roots=roots,
        )

    # A project-local manifest lets uninstall remove only files whose bytes
    # still match the installer. It deliberately excludes user-owned templates.
    previous = read_valid_manifest(manifest_path)
    previous_managed, rejected_records = validated_managed_records(previous, project, codex_home)
    for path, reason in rejected_records.items():
        plan.warnings.append(f"ignored manifest entry {path}: {reason}; existing data is preserved")
    managed: dict[str, str] = dict(previous_managed)
    for item in plan.items:
        if item.kind not in (MANAGED, FORCE_PROTECTED) or item.content is None or item.origin == "install-manifest":
            continue
        path = str(item.path.resolve())
        desired_hash = hashlib.sha256(item.content).hexdigest()
        # Exact pre-existing bytes do not prove installer ownership. Carry
        # ownership forward only when the previous manifest already recorded
        # the same bytes; otherwise track files this run creates or replaces.
        if item.action != UNCHANGED or previous_managed.get(path) == desired_hash:
            managed[path] = desired_hash
    manifest_data = {"version": 1, "files": managed}
    manifest_data["manifest_sha256"] = hashlib.sha256(
        json.dumps(manifest_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest = json.dumps(manifest_data, indent=2, sort_keys=True) + "\n"
    add_generated_plan(
        plan,
        manifest_path,
        origin="install-manifest",
        content=manifest.encode("utf-8"),
        roots=roots,
    )

    if prune and skill_dest.is_dir():
        planned = {item.path.resolve() for item in plan.items}
        # Never let a correctly checksummed manifest expand our ownership scope.
        # Iterate validated exact records, not arbitrary files beneath the skill.
        for raw_path, expected_hash in sorted(previous_managed.items()):
            existing = Path(raw_path)
            if skill_dest not in existing.parents or existing in planned:
                continue
            validate_destination(existing, roots)
            current = read_existing(existing)
            if current is not None and hashlib.sha256(current).hexdigest() == expected_hash:
                plan.add(
                    PlanItem(
                        action=REMOVE,
                        path=existing,
                        origin="skill-prune",
                        note="unchanged known managed file, not part of this bundle",
                        expected_hash=expected_hash,
                    )
                )

    roots = (project.resolve(), codex_home.resolve())
    for item in plan.items:
        validate_destination(item.path, roots)

    return plan


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def atomic_write(
    dest: Path, content: bytes, backup: bool, roots: tuple[Path, ...], *,
    no_clobber: bool = False, expected_hash: Optional[str] = None,
) -> None:
    """Stage bytes beside the target; CREATE uses an atomic no-clobber link."""
    validate_destination(dest, roots)
    dest.parent.mkdir(parents=True, exist_ok=True)
    validate_destination(dest, roots)
    if no_clobber and (dest.exists() or is_reparse_point(dest)):
        raise FileExistsError(f"destination appeared after planning: {dest}")
    if not no_clobber:
        try:
            current = dest.read_bytes()
        except FileNotFoundError:
            current = None
        if expected_hash is not None and (current is None or hashlib.sha256(current).hexdigest() != expected_hash):
            raise InstallError(f"destination changed after planning; refusing update: {dest}")
        if backup and current is not None:
            index = 0
            while True:
                suffix = ".bak" if index == 0 else f".bak.{index}"
                backup_path = dest.with_name(dest.name + suffix)
                validate_destination(backup_path, roots)
                try:
                    with backup_path.open("xb") as stream:
                        stream.write(current)
                    shutil.copystat(dest, backup_path)
                    break
                except FileExistsError:
                    index += 1
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".tmp-install", dir=str(dest.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        validate_destination(dest, roots)
        if no_clobber:
            # Same-volume hardlink creation is atomic and cannot replace a race winner.
            os.link(temporary, dest)
            temporary.unlink()
        else:
            if is_reparse_point(dest):
                raise InstallError(f"destination became a symlink or junction: {dest}")
            try:
                current = dest.read_bytes()
            except FileNotFoundError:
                current = None
            if expected_hash is not None and (current is None or hashlib.sha256(current).hexdigest() != expected_hash):
                raise InstallError(f"destination changed after planning; refusing update: {dest}")
            os.replace(temporary, dest)
    except Exception:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def apply_plan(plan: Plan, *, force: bool, dry_run: bool, roots: tuple[Path, ...]) -> dict:
    written: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    preserved: list[str] = []
    unchanged: list[str] = []

    for item in plan.items:
        # A conflict is only unresolved without --force; the caller already
        # returned exit code 3 in that case, so here it means "replace".
        if item.action == CONFLICT and force and item.kind != FORCE_PROTECTED:
            item.action = UPDATE
        if item.action == UNCHANGED:
            unchanged.append(item.display_path())
            continue
        if item.action == PRESERVE:
            preserved.append(item.display_path())
            continue
        if item.action == CONFLICT:
            continue
        if item.action == REMOVE:
            validate_destination(item.path, roots)
            current = read_existing(item.path)
            if item.expected_hash is None or current is None or hashlib.sha256(current).hexdigest() != item.expected_hash:
                preserved.append(item.display_path())
                plan.warnings.append(f"kept {item.path}: file changed since the prune plan")
                continue
            if dry_run:
                removed.append(item.display_path())
                continue
            try:
                item.path.unlink()
                removed.append(item.display_path())
            except OSError as exc:
                plan.warnings.append(f"could not remove {item.path}: {exc}")
            continue

        if item.action == CREATE:
            if dry_run:
                written.append(item.display_path())
                continue
            content = (
                item.content
                if item.content is not None
                else read_source(item.source)  # type: ignore[arg-type]
            )
            try:
                atomic_write(item.path, content, backup=False, roots=roots, no_clobber=True)
                written.append(item.display_path())
            except FileExistsError:
                preserved.append(item.display_path())
                plan.warnings.append(f"preserved {item.path}: destination appeared after planning")
        elif item.action == UPDATE:
            if dry_run:
                updated.append(item.display_path())
                continue
            content = (
                item.content
                if item.content is not None
                else read_source(item.source)  # type: ignore[arg-type]
            )
            atomic_write(item.path, content, backup=force, roots=roots, expected_hash=item.expected_hash)
            updated.append(item.display_path())

    return {
        "created": written,
        "updated": updated,
        "removed": removed,
        "preserved": preserved,
        "unchanged": unchanged,
        "warnings": plan.warnings,
    }


def apply_install_plan(
    plan: Plan, *, force: bool, project: Path, codex_home: Path,
    roots: tuple[Path, ...],
) -> dict:
    """Apply one locked install and record only completed file actions."""
    manifest_path = project / ".codex" / MANIFEST_NAME
    previous = read_valid_manifest(manifest_path)
    previous_files, rejected = validated_managed_records(previous, project, codex_home)
    files = dict(previous_files)
    registry = read_registry(codex_home)
    result = {"created": [], "updated": [], "removed": [], "preserved": [], "unchanged": [], "warnings": []}
    for raw, reason in rejected.items():
        result["warnings"].append(f"ignored manifest entry {raw}: {reason}; existing data is preserved")

    for item in plan.items:
        if item.origin == "install-manifest":
            continue
        if item.action == CONFLICT and force and item.kind != FORCE_PROTECTED:
            item.action = UPDATE
        if item.action == CONFLICT:
            continue
        raw_path = str(Path(os.path.abspath(item.path)))
        shared = is_shared_path(item.path, codex_home)
        existing_record = registry["files"].get(raw_path)
        before = item.action

        if item.action == REMOVE and shared:
            other_owners = [owner for owner in (existing_record or {}).get("owners", []) if owner != str(project)]
            if other_owners:
                drop_registry_owner(registry, raw_path, project)
                files.pop(raw_path, None)
                write_json_atomic(codex_home / REGISTRY_NAME, registry, roots)
                write_manifest(project, codex_home, files)
                result["preserved"].append(raw_path)
                continue

        delta = apply_plan(Plan(items=[item]), force=force, dry_run=False, roots=roots)
        for key in ("created", "updated", "removed", "preserved", "unchanged"):
            result[key].extend(delta[key])
        result["warnings"].extend(delta["warnings"])

        if item.action == REMOVE:
            if raw_path in result["removed"]:
                files.pop(raw_path, None)
                if shared:
                    drop_registry_owner(registry, raw_path, project)
                    write_json_atomic(codex_home / REGISTRY_NAME, registry, roots)
            write_manifest(project, codex_home, files)
            continue

        if item.kind not in (MANAGED, FORCE_PROTECTED) or item.content is None:
            continue
        desired_hash = hashlib.sha256(item.content).hexdigest()
        completed = (before in (CREATE, UPDATE) and (raw_path in result["created"] or raw_path in result["updated"])) or (before == UNCHANGED and raw_path in result["unchanged"])
        if not completed:
            continue
        try:
            actual_hash = hashlib.sha256(item.path.read_bytes()).hexdigest()
        except OSError:
            continue
        if actual_hash != desired_hash:
            continue
        if shared:
            owners = (existing_record or {}).get("owners", [])
            already_claimed = previous_files.get(raw_path) == desired_hash or str(project) in owners
            if before in (CREATE, UPDATE) or already_claimed or owners:
                files[raw_path] = desired_hash
                set_registry_owner(registry, raw_path, desired_hash, project)
                write_json_atomic(codex_home / REGISTRY_NAME, registry, roots)
        elif before in (CREATE, UPDATE) or previous_files.get(raw_path) == desired_hash:
            files[raw_path] = desired_hash
        write_manifest(project, codex_home, files)

    if not manifest_path.exists():
        write_manifest(project, codex_home, files)
    result["warnings"].extend(plan.warnings)
    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_plan(plan: Plan, codex_home: Path, project: Path) -> str:
    lines = [
        f"repository  : {REPO_ROOT}",
        f"codex home  : {codex_home}",
        f"project     : {project}",
        "",
        f"{'ACTION':<10} {'ORIGIN':<15} PATH",
    ]
    for item in plan.items:
        suffix = f"  ({item.note})" if item.note else ""
        lines.append(
            f"{item.action:<10} {item.origin:<15} {item.display_path()}{suffix}"
        )
    if plan.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    return "\n".join(lines)


def remediation_hint(conflicts: list[PlanItem]) -> str:
    lines = [
        "",
        "Nothing was written. These files already exist with different content:",
    ]
    lines.extend(f"- {item.display_path()}" for item in conflicts)
    lines.extend(
        [
            "",
            "Options:",
            "  * re-run with --force to replace conflicting managed files; each",
            "    replacement is backed up next to the original as .bak",
            "  * delete the listed files yourself, then re-run without --force",
            "  * point --codex-home or --project somewhere else",
            "",
            "PROJECT_STATE.md and AGENTS.md are user-owned and are never overwritten.",
            "An existing project hooks.json is never replaced, even with --force.",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    project = Path(args.project).expanduser()
    if is_reparse_point(project):
        raise InstallError(f"--project is a symlink or junction: {project}")
    if not project.exists():
        raise InstallError(f"--project does not exist: {project}")
    if not project.is_dir():
        raise InstallError(f"--project is not a directory: {project}")
    project = project.resolve()

    codex_home_raw = args.codex_home or os.environ.get("CODEX_HOME")
    if not codex_home_raw:
        raise InstallError(
            "no Codex home given. Pass --codex-home PATH or set CODEX_HOME. "
            "The installer refuses to guess, because writing into the wrong "
            "directory is not recoverable for the user."
        )
    home_input = Path(codex_home_raw).expanduser()
    if is_reparse_point(home_input):
        raise InstallError(f"--codex-home is a symlink or junction: {home_input}")
    codex_home = home_input.resolve()
    return project, codex_home


def parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description=(
            "Install the native Codex orchestrator skill and role agents, "
            "project state template, and optional project hooks."
        ),
    )
    parser.add_argument("--project", required=True, help="target project root")
    parser.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory (falls back to the CODEX_HOME variable)",
    )
    parser.add_argument(
        "--hooks",
        action="store_true",
        help="also install project-local state hooks and .codex/hooks.json",
    )
    parser.add_argument("--data-dir", help="embed a previously bound project-contained ledger directory in generated hook commands; does not bind it")
    parser.add_argument(
        "--agents-md",
        action="store_true",
        help="also drop the example AGENTS.md into the project root",
    )
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="skip the six child-agent TOML files; the main-session director profile is still installed",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace managed files that differ, backing each one up as .bak",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="remove unchanged recorded files at known managed skill paths missing from this bundle; preserve unknown paths",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and exit without writing anything",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the plan and result as JSON instead of a table",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        project, codex_home = resolve_paths(args)
        with installation_lock(codex_home):
            return _install_locked(args, project, codex_home)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


def _install_locked(args: argparse.Namespace, project: Path, codex_home: Path) -> int:
    plan = Plan()
    try:
        build_plan(
            project,
            codex_home,
            with_hooks=args.hooks,
            data_dir=args.data_dir,
            with_agents_md=args.agents_md,
            with_agent=not args.no_agent,
            prune=args.prune,
            plan=plan,
        )
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not (project / ".git").exists():
        plan.warnings.append(
            "project does not look like a git repository (no .git directory); "
            "the Stop hook needs git to detect repository changes."
        )
    if not (codex_home / "config.toml").exists():
        plan.warnings.append(
            f"no config.toml found in {codex_home}; the installer still writes "
            "there, but double-check that this is your real Codex home."
        )

    conflicts = plan.conflicts()
    blocked_conflicts = plan.blocked_conflicts(args.force)
    blocked = bool(blocked_conflicts)

    if args.json:
        payload = {
            "status": (
                "conflict" if blocked else ("planned" if args.dry_run else "ok")
            ),
            "repository": str(REPO_ROOT),
            "codex_home": str(codex_home),
            "project": str(project),
            "actions": [
                {
                    "action": item.action,
                    "origin": item.origin,
                    "path": item.display_path(),
                }
                for item in plan.items
            ],
            "conflicts": [item.display_path() for item in conflicts],
            "blocking_conflicts": [item.display_path() for item in blocked_conflicts],
            "warnings": plan.warnings,
            "exit_code": EXIT_CONFLICT if blocked else EXIT_OK,
        }
        if not blocked and not args.dry_run:
            try:
                payload["result"] = apply_install_plan(
                    plan, force=args.force, project=project, codex_home=codex_home,
                    roots=(project.resolve(), codex_home.resolve()),
                )
            except (InstallError, OSError) as exc:
                payload["status"] = "partial_error"
                payload["error"] = str(exc)
                payload["exit_code"] = EXIT_ERROR
                print(json.dumps(payload, indent=2))
                return EXIT_ERROR
        print(json.dumps(payload, indent=2))
        return EXIT_CONFLICT if blocked else EXIT_OK

    print(render_plan(plan, codex_home, project))

    if blocked:
        print(remediation_hint(blocked_conflicts))
        return EXIT_CONFLICT

    if args.dry_run:
        print("\nDry run: nothing was written.")
        return EXIT_OK

    try:
        result = apply_install_plan(
            plan, force=args.force, project=project, codex_home=codex_home,
            roots=(project.resolve(), codex_home.resolve()),
        )
    except (InstallError, OSError) as exc:
        print(f"error: partial install: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print("")
    print(f"created   : {len(result['created'])}")
    print(f"updated   : {len(result['updated'])}")
    print(f"removed   : {len(result['removed'])}")
    print(f"preserved : {len(result['preserved'])}")
    print(f"unchanged : {len(result['unchanged'])}")
    for warning in result["warnings"]:
        print(f"warning   : {warning}")

    if args.hooks:
        print("")
        print("Hooks installed at project scope. Review and trust them with /hooks")
        print("before they run, and re-run this installer after moving the repo.")

    print("")
    print("Next: restart or reopen Codex so the skill and agent are picked up,")
    print("then read QUICKSTART.md for the first dispatch.")
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
