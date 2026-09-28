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
import sys
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
    for directory in (current, *current.parents):
        candidate = directory / STATE_RELATIVE
        if candidate.is_file():
            return candidate
    return None


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


def build_context(state_path: Path, text: str) -> str:
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
    return f"{header}\n---\n{text}\n---\n(state file: {state_path})\n"


def main() -> int:
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
            "additionalContext": build_context(state_path, text),
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
