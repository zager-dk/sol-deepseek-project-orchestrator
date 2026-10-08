#!/usr/bin/env python3
"""Ask for one state-update pass when the repository changed and state is stale.

Wired to the Stop hook event. Codex sends one JSON object on stdin and expects
JSON on stdout:

    {"decision": "block", "reason": "..."}

`decision: "block"` on Stop does not reject the turn. It tells Codex to continue
and turns `reason` into a fresh prompt, so this hook is deliberately quiet and
fires at most once per turn:

  * stop_hook_active is true  -> allow the turn to end (Codex already continued)
  * a nudge was already sent for this turn id -> allow
  * no git repository, or git missing -> allow
  * no repository changes -> allow
  * PROJECT_STATE.md is missing -> nudge once
  * PROJECT_STATE.md is newer than every changed path -> allow
  * a present snapshot helper fails -> issue one diagnostic continuation,
    because an unverifiable snapshot is not evidence that state is current

The snapshot-failure diagnostic uses the normal one-shot turn marker. A later
Stop callback with stop_hook_active is always allowed, preventing a loop. The
hook only reads PROJECT_STATE.md; it never edits the state file itself.

Environment:
    SOL_DEEPSEEK_DISABLE_STATE_HOOK=1   disable the nudge without uninstalling
    SOL_DEEPSEEK_NUDGE_DIR=path         where one-shot turn markers are kept
"""

from __future__ import annotations

import json
import hashlib
import re
import os
import stat
import subprocess
import sys
import argparse
import tempfile
from pathlib import Path

STATE_RELATIVE = Path(".codex") / "PROJECT_STATE.md"
GIT_TIMEOUT_SECONDS = 10

REASON = (
    "Repository changes were made during this turn and .codex/PROJECT_STATE.md "
    "was not updated afterward. Before ending the turn, update the durable "
    "state in place if anything durable changed: current milestone, "
    "architecture or public contracts, decisions and non-goals, known "
    "risks, verification baseline, next steps. Replace stale bullets instead "
        "of appending a diary, and keep the file compact. If nothing durable "
    "changed, say so in one line and stop; do not invent state."
)

SNAPSHOT_FAILURE_REASON = (
    "The project snapshot could not be verified. Resolve the snapshot helper "
    "error and retry before ending this turn. The hook did not update "
    ".codex/PROJECT_STATE.md."
)


class SnapshotFailure(RuntimeError):
    """A bundled snapshot helper exists but could not verify project state."""


def read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_root(start: Path) -> Path | None:
    result = run_git(["rev-parse", "--show-toplevel"], start)
    if result is None or result.returncode != 0:
        return None
    line = result.stdout.strip().splitlines()
    if not line:
        return None
    try:
        return Path(line[0]).resolve()
    except OSError:
        return None

def safe_codex_dir(root: Path) -> bool:
    directory=root/'.codex'
    try:
        info=directory.lstat()
        flag=getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&flag) or bool(getattr(directory,'is_junction',lambda:False)()): return False
        directory.resolve(strict=False).relative_to(root.resolve())
        return directory.is_dir()
    except FileNotFoundError:
        return True
    except (OSError,ValueError):
        return False

def unsafe_link(path: Path) -> bool:
    try:
        info=path.lstat(); flag=getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&flag) or bool(getattr(path,'is_junction',lambda:False)())
    except OSError:
        return False


def changed_paths(root: Path) -> list[Path]:
    result = run_git(["status", "--porcelain"], root)
    if result is None or result.returncode != 0:
        return []
    changed: list[Path] = []
    for raw_line in result.stdout.splitlines():
        entry = raw_line[3:].strip()
        if not entry:
            continue
        # Renames are reported as "old -> new"; the new path is what changed.
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        entry = entry.strip('"')
        candidate = root / entry
        if candidate.exists():
            changed.append(candidate)
    return changed


def safe_runtime_helper(path: Path, root: Path) -> bool:
    try:
        root = root.resolve()
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if unsafe_link(current): return False
        current.resolve().relative_to(root)
        return current.is_file()
    except (OSError, ValueError):
        return False


def orchestration_snapshot(root: Path, data_dir: str | None = None) -> dict | None:
    """Use the one canonical fingerprint implementation shipped with hooks."""
    if not safe_codex_dir(root):
        raise SnapshotFailure("project .codex path is unsafe")
    root = root.resolve()
    candidates = (root / '.codex' / 'hooks' / 'orchestrate.py', root / 'scripts' / 'orchestrate.py')
    helper = next((path for path in candidates if safe_runtime_helper(path, root)), None)
    if helper is None:
        return None
    try:
        command=[sys.executable, str(helper), '--project', str(root)]
        if data_dir: command += ['--data-dir', data_dir]
        command += ['snapshot','--json']
        result = subprocess.run(
            command,
            cwd=str(root), capture_output=True, text=True, timeout=GIT_TIMEOUT_SECONDS, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SnapshotFailure("snapshot helper could not be run") from exc
    if result.returncode != 0:
        raise SnapshotFailure(f"snapshot helper exited with status {result.returncode}")
    try:
        value = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise SnapshotFailure("snapshot helper returned invalid JSON") from exc
    if not isinstance(value, dict) or not isinstance(value.get('state_fingerprint'), str):
        raise SnapshotFailure("snapshot helper output did not include a state fingerprint")
    return value


def recorded_fingerprint(state_path: Path) -> str | None:
    try:
        text = state_path.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return None
    match = re.search(r'<!--\s*orchestrator-snapshot:([0-9a-f]{64})\s*-->', text)
    return match.group(1) if match else None


def newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for path in paths:
        try:
            if path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        newest = max(newest, child.stat().st_mtime)
            else:
                newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def nudge_already_sent(turn_id: str) -> bool:
    if not turn_id:
        return False
    base = os.environ.get("SOL_DEEPSEEK_NUDGE_DIR")
    directory = Path(base) if base else Path(tempfile.gettempdir()) / "sol-deepseek-state-nudge"
    key = hashlib.sha256(turn_id.encode('utf-8')).hexdigest()
    marker = directory / f"{key}.sent"
    try:
        if marker.exists():
            return True
        directory.mkdir(parents=True, exist_ok=True)
        marker.write_text("sent\n", encoding="utf-8")
    except OSError:
        # If the marker cannot be written we still allow one nudge; the
        # stop_hook_active guard below prevents a loop.
        return False
    return False


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--data-dir'); args=parser.parse_args()
    if os.environ.get("SOL_DEEPSEEK_DISABLE_STATE_HOOK"):
        return 0

    payload = read_payload()
    if payload.get("stop_hook_active"):
        return 0

    cwd_raw = payload.get("cwd")
    start = Path(cwd_raw) if isinstance(cwd_raw, str) and cwd_raw else Path.cwd()
    if not start.is_dir():
        return 0

    root = git_root(start)
    if root is None:
        return 0

    changed = changed_paths(root)
    if not safe_codex_dir(root): return 0
    state_path = root / STATE_RELATIVE
    if unsafe_link(state_path): return 0
    if not state_path.is_file():
        if not changed: return 0
        decision = {
            "decision": "block",
            "reason": (
                "This repository changed during the turn but has no "
                ".codex/PROJECT_STATE.md. Create it from the project state "
                "template with the current intent, milestone, contracts, "
                "risks, verification baseline, and next steps. Keep it compact."
            ),
        }
    else:
        try:
            current = orchestration_snapshot(root, args.data_dir)
        except SnapshotFailure as exc:
            # A failed canonical snapshot is unknown state, never evidence that
            # the project state is current. Emit one diagnostic continuation.
            decision = {
                "decision": "block",
                "reason": f"{SNAPSHOT_FAILURE_REASON}\nDiagnostic: {exc}",
            }
        else:
            recorded = recorded_fingerprint(state_path)
            if current is not None:
                if recorded and recorded == current.get('state_fingerprint'):
                    return 0
                if not changed and not recorded:
                    return 0
            else:
                if not changed: return 0
                # Older/manual installs may contain the hook without its helper.
                # Keep their timestamp behavior until the helper is installed.
                try: state_mtime = state_path.stat().st_mtime
                except OSError: return 0
                newest = newest_mtime([p for p in changed if p.resolve() != state_path.resolve()])
                if newest <= state_mtime:
                    return 0
            paths = current.get('paths', []) if current else []
            affected = ', '.join(paths[:20]) or ('HEAD changed with no dirty paths' if current and recorded else 'snapshot unavailable or state has no snapshot marker')
            suffix = f"\nAffected paths (inspect these first): {affected}"
            if len(paths) > 20:
                suffix += f" (+{len(paths) - 20} more)"
            decision = {"decision": "block", "reason": REASON + suffix}

    turn_id = payload.get("turn_id")
    turn_key = turn_id if isinstance(turn_id, str) else ""
    if turn_key and nudge_already_sent(turn_key):
        return 0

    try:
        json.dump(decision, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    except (OSError, ValueError) as exc:
        print(f"stop_project_state_check: cannot write output: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # never trap the user in a turn because of a hook
        print(f"stop_project_state_check: unexpected failure: {exc!r}", file=sys.stderr)
        raise SystemExit(0)
