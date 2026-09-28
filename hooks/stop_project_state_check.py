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

Every failure path exits 0 with no stdout or an empty object, because a broken
safety net must never block a user's turn.

Environment:
    SOL_DEEPSEEK_DISABLE_STATE_HOOK=1   disable the nudge without uninstalling
    SOL_DEEPSEEK_NUDGE_DIR=path         where one-shot turn markers are kept
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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
    marker = directory / f"{turn_id}.sent"
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
    if not changed:
        return 0

    state_path = root / STATE_RELATIVE
    if not state_path.is_file():
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
            state_mtime = state_path.stat().st_mtime
        except OSError:
            return 0
        newest = newest_mtime([p for p in changed if p.resolve() != state_path.resolve()])
        if newest <= state_mtime:
            return 0
        decision = {"decision": "block", "reason": REASON}

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
