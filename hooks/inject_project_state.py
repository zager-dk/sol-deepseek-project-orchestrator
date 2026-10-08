#!/usr/bin/env python3
"""Inject .codex/PROJECT_STATE.md into the session as developer context.

Wired to the SessionStart hook event, with the matcher
`startup|resume|clear|compact`. The `compact` source is what covers the window
after compaction: Codex runs matching SessionStart hooks before the next model
request, including when automatic compaction happens mid-turn. PostCompact is
deliberately not used, because that event only supports the common output
fields and cannot carry `additionalContext`.

Codex sends one JSON object on stdin and reads JSON from stdout, so this script
is careful to keep stdout valid:

    {"hookSpecificOutput": {"hookEventName": "...", "additionalContext": "..."}}

Every failure path exits 0 with no stdout, because a broken memory hook must
never break a session. Diagnostics go to stderr.

Environment:
    SOL_DEEPSEEK_DISABLE_STATE_HOOK=1   disable injection without uninstalling
    SOL_DEEPSEEK_STATE_MAX_BYTES=N      override the injected size cap
"""

from __future__ import annotations

import json
import os
import subprocess
import re
import stat
import sys
import argparse
from pathlib import Path

DEFAULT_MAX_BYTES = 12000
WARN_BYTES = 14000
STATE_RELATIVE = Path(".codex") / "PROJECT_STATE.md"


def find_state_file(start: Path) -> Path | None:
    """Walk up from `start` looking for the nearest .codex/PROJECT_STATE.md."""
    try:
        current = start.resolve()
    except OSError:
        return None
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=current,
                                capture_output=True, text=True, timeout=5, check=False)
        boundary = Path(result.stdout.strip()).resolve() if result.returncode == 0 else current
    except (OSError, subprocess.SubprocessError):
        boundary = current
    for directory in (current, *current.parents):
        candidate = directory / STATE_RELATIVE
        if safe_codex_dir(directory / '.codex') and not unsafe_link(candidate) and candidate.is_file():
            return candidate
        if directory == boundary:
            break
    return None

def safe_codex_dir(path: Path) -> bool:
    """Do not follow a project state directory through a symlink or junction."""
    try:
        info=path.lstat()
        flag=getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
        if stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&flag) or bool(getattr(path,'is_junction',lambda:False)()): return False
        return path.is_dir()
    except FileNotFoundError:
        return True
    except OSError:
        return False

def safe_helper(path: Path, root: Path) -> bool:
    """Require every helper path component to stay inside the Git root."""
    try:
        root = root.resolve()
        relative = path.relative_to(root)
        current = root
        for part in relative.parts:
            current = current / part
            if unsafe_link(current):
                return False
        current.resolve().relative_to(root)
        return current.is_file()
    except (OSError, ValueError):
        return False


def unsafe_link(path: Path) -> bool:
    try:
        info=path.lstat()
        flag=getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',0x400)
        return stat.S_ISLNK(info.st_mode) or bool(getattr(info,'st_file_attributes',0)&flag) or bool(getattr(path,'is_junction',lambda:False)())
    except OSError:
        return False


def read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def max_bytes() -> int:
    raw = os.environ.get("SOL_DEEPSEEK_STATE_MAX_BYTES", "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_BYTES
    return value if value > 0 else DEFAULT_MAX_BYTES


def build_context(state_path: Path, text: str, data_dir: str | None = None) -> str:
    limit = max_bytes()
    encoded = text.encode("utf-8")
    notes: list[str] = []

    if len(encoded) > limit:
        keep = max(limit // 2, 512)
        head = encoded[:keep].decode("utf-8", errors="replace")
        tail = encoded[-keep:].decode("utf-8", errors="replace")
        text = (
            f"{head}\n\n[... truncated by inject_project_state.py: "
            f"{len(encoded)} bytes total, {limit} byte cap ...]\n\n{tail}"
        )
        notes.append(
            "This state file is larger than the injected cap. Compact it and "
            "remove stale bullets."
        )
    elif len(encoded) > WARN_BYTES:
        notes.append(
            "This state file is close to or past the recommended 10 KB. Compact "
            "it and remove stale bullets."
        )

    header = (
        "# Durable project state (injected from .codex/PROJECT_STATE.md)\n\n"
        "This is the canonical working memory for the project. Prefer it over "
        "chat history. It is state, not history: update it in place and delete "
        "stale bullets.\n"
    )
    if notes:
        header += "\nNotes:\n" + "".join(f"- {note}\n" for note in notes)
    stale = stale_snapshot_note(state_path, data_dir)
    if stale:
        header += f"\nFreshness: {stale}\n"
    return f"{header}\n---\n{text}\n---\n(state file: {state_path})\n"

def stale_snapshot_note(state_path: Path, data_dir: str | None = None) -> str | None:
    """Ask the canonical helper for freshness, avoiding a second hash algorithm."""
    root=state_path.parent.parent
    if not safe_codex_dir(root/'.codex'): return 'state path is unsafe; it is not being trusted'
    root = root.resolve()
    candidates=(root/'.codex'/'hooks'/'orchestrate.py',root/'scripts'/'orchestrate.py')
    helper=next((p for p in candidates if safe_helper(p, root)),None)
    if helper is None: return None
    try:
        command=[sys.executable,str(helper),'--project',str(root)]
        if data_dir: command += ['--data-dir',data_dir]
        command += ['snapshot','--json']
        result=subprocess.run(command,cwd=root,capture_output=True,text=True,timeout=5,check=False)
        data=json.loads(result.stdout) if result.returncode==0 else None
        state=state_path.read_text(encoding='utf-8',errors='replace')
        match=re.search(r'<!--\s*orchestrator-snapshot:([0-9a-f]{64})\s*-->',state)
        if not isinstance(data,dict) or not data.get('state_fingerprint'):
            return 'snapshot could not be verified; check affected paths before relying on this state'
        if not match: return 'snapshot marker is missing; check affected paths before relying on this state'
        if match.group(1)==data['state_fingerprint']: return None
        paths=data.get('paths',[])
        return 'snapshot is stale; inspect affected paths first: '+(', '.join(paths[:20]) if paths else 'HEAD changed with no dirty paths')
    except (OSError,subprocess.SubprocessError,ValueError):
        return 'snapshot could not be verified; check affected paths before relying on this state'


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--data-dir'); args=parser.parse_args()
    if os.environ.get("SOL_DEEPSEEK_DISABLE_STATE_HOOK"):
        return 0

    payload = read_payload()
    event = payload.get("hook_event_name") or "SessionStart"
    if not isinstance(event, str) or event != "SessionStart":
        event = "SessionStart"

    cwd = payload.get("cwd")
    start = Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd()

    state_path = find_state_file(start)
    if state_path is None:
        return 0

    try:
        text = state_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"inject_project_state: cannot read {state_path}: {exc}", file=sys.stderr)
        return 0

    if not text.strip():
        return 0

    output = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": build_context(state_path, text, args.data_dir),
        }
    }
    try:
        json.dump(output, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    except (OSError, ValueError) as exc:
        print(f"inject_project_state: cannot write output: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # never break the session because of a memory hook
        print(f"inject_project_state: unexpected failure: {exc!r}", file=sys.stderr)
        raise SystemExit(0)
