#!/usr/bin/env python3
"""Check an installed layout and optionally smoke-test the hooks.

Exit codes: 0 when no errors are found, 1 when something is missing or broken.
Warnings do not fail the check.

Examples:
    python scripts/verify_install.py --project /path/to/repo --codex-home ~/.codex
    python scripts/verify_install.py --project . --codex-home ~/.codex --self-test
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

SKILL_NAME = "sol-deepseek-project-orchestrator"
AGENT_FILE_NAME = "deepseek-worker.toml"

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_ERROR = 2


class UsageError(Exception):
    pass


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.checks: list[tuple[str, str, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        status = "ok" if ok else "error"
        self.checks.append((status, name, detail))
        if not ok:
            self.errors.append(f"{name}: {detail}" if detail else name)
        return ok

    def warn(self, name: str, detail: str) -> None:
        self.checks.append(("warn", name, detail))
        self.warnings.append(f"{name}: {detail}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="verify_install.py",
        description="Verify an installed orchestrator layout.",
    )
    parser.add_argument("--project", required=True, help="target project root")
    parser.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory (falls back to the CODEX_HOME variable)",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run the installed hooks against a throwaway git repository",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser.parse_args(argv)


def check_layout(project: Path, codex_home: Path, report: Report) -> None:
    skill_dir = codex_home / "skills" / SKILL_NAME
    report.check("skill directory", skill_dir.is_dir(), str(skill_dir))
    report.check(
        "skill SKILL.md", (skill_dir / "SKILL.md").is_file(), str(skill_dir / "SKILL.md")
    )
    report.check(
        "skill ARCHITECTURE.md",
        (skill_dir / "ARCHITECTURE.md").is_file(),
        "the long-form design document ships with the skill",
    )
    for reference in ("DELEGATION_CONTRACT.md", "STATE_POLICY.md", "ROUTING.md"):
        path = skill_dir / "references" / reference
        report.check(f"skill reference {reference}", path.is_file(), str(path))

    agent = codex_home / "agents" / AGENT_FILE_NAME
    if agent.is_file():
        text = agent.read_text(encoding="utf-8", errors="replace")
        report.check("agent declares deepseek_worker", 'name = "deepseek_worker"' in text)
        report.check(
            "agent declares a model",
            "model = " in text,
            "model line is required for explicit routing",
        )
        report.warn(
            "agent model id",
            "confirm the model slug against your own router catalog; the "
            "bundled slug is router-supplied and may differ",
        )
    else:
        report.warn("custom agent", f"not installed at {agent}")

    state = project / ".codex" / "PROJECT_STATE.md"
    if state.is_file():
        size = state.stat().st_size
        report.check("project state present", True, f"{size} bytes")
        if size > 14000:
            report.warn("project state size", f"{size} bytes; compact it under 10 KB")
        elif size > 10000:
            report.warn("project state size", f"{size} bytes; target is under 10 KB")
    else:
        report.warn("project state", f"missing at {state}")

    hooks_json = project / ".codex" / "hooks.json"
    if hooks_json.is_file():
        try:
            data = json.loads(hooks_json.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            report.check("hooks.json parses", False, str(exc))
            return
        report.check("hooks.json parses", True)
        events = data.get("hooks", {}) if isinstance(data, dict) else {}
        report.check(
            "hooks.json declares SessionStart", "SessionStart" in events
        )
        report.check("hooks.json declares Stop", "Stop" in events)
        for event, groups in events.items():
            for group in groups if isinstance(groups, list) else []:
                for handler in group.get("hooks", []):
                    command = handler.get("command")
                    if not isinstance(command, str):
                        continue
                    script = command.split('"')
                    candidate = script[1] if len(script) > 1 else command.split()[-1]
                    report.check(
                        f"{event} hook script exists",
                        Path(candidate).is_file(),
                        candidate,
                    )
    else:
        report.warn("project hooks", f"no {hooks_json}; run install.py --hooks to add them")


def hook_self_test(project: Path, report: Report) -> None:
    """Run the installed hooks in a throwaway git repo."""
    hooks_dir = project / ".codex" / "hooks"
    inject = hooks_dir / "inject_project_state.py"
    stop = hooks_dir / "stop_project_state_check.py"
    for script in (inject, stop):
        if not script.is_file():
            report.warn("self-test", f"skipped, missing {script}")
            return

    with tempfile.TemporaryDirectory(prefix="sol-deepseek-verify-") as raw:
        sandbox = Path(raw)
        # The Stop hook fires at most once per turn id. Point the one-shot
        # markers at this throwaway sandbox so repeated self-tests behave the
        # same way and the user's real marker directory is left alone.
        hook_env = {"SOL_DEEPSEEK_NUDGE_DIR": str(sandbox / "nudge-markers")}
        state_dir = sandbox / ".codex"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "PROJECT_STATE.md").write_text(
            "# Project State\n\n## Project intent\nverify hook\n",
            encoding="utf-8",
        )
        git_ok = _try_git_init(sandbox)

        payload = json.dumps(
            {"hook_event_name": "SessionStart", "cwd": str(sandbox)}
        )
        result = _run_hook(inject, payload, sandbox)
        if result is None:
            report.check("self-test inject runs", False, "process did not start")
            return
        report.check("self-test inject exit code", result.returncode == 0, str(result.returncode))
        try:
            data = json.loads(result.stdout or "{}")
            context = data["hookSpecificOutput"]["additionalContext"]
            ok = "verify hook" in context
        except (ValueError, KeyError, TypeError):
            ok = False
            context = ""
        report.check(
            "self-test inject returns state context",
            ok,
            "stdout must be hook JSON with additionalContext",
        )

        result = _run_hook(
            stop,
            json.dumps({"cwd": str(sandbox), "turn_id": f"verify-{uuid.uuid4()}"}),
            sandbox,
            env=hook_env,
        )
        if result is None:
            report.check("self-test stop runs", False, "process did not start")
            return
        report.check(
            "self-test stop silent on a clean tree",
            not (result.stdout or "").strip(),
            f"stdout={result.stdout!r}",
        )

        if not git_ok:
            report.warn("self-test", "git unavailable; skipped the change-detection check")
            return

        tracked = sandbox / "app.txt"
        tracked.write_text("v1\n", encoding="utf-8")
        _git(sandbox, ["add", "-A"])
        _git(sandbox, ["-c", "user.email=verify@example.invalid", "-c", "user.name=verify", "commit", "-m", "init"])
        tracked.write_text("v2\n", encoding="utf-8")
        os.utime(state_dir / "PROJECT_STATE.md", (1, 1))
        result = _run_hook(
            stop,
            json.dumps({"cwd": str(sandbox), "turn_id": f"verify-{uuid.uuid4()}"}),
            sandbox,
            env=hook_env,
        )
        if result is None:
            report.check("self-test stop change detection", False, "process did not start")
            return
        try:
            decision = json.loads((result.stdout or "").strip() or "{}")
        except ValueError:
            decision = {}
        report.check(
            "self-test stop nudges on a stale state file",
            decision.get("decision") == "block",
            f"stdout={(result.stdout or '').strip()!r}",
        )
        result = _run_hook(
            stop,
            json.dumps(
                {
                    "cwd": str(sandbox),
                    "turn_id": f"verify-{uuid.uuid4()}",
                    "stop_hook_active": True,
                }
            ),
            sandbox,
            env=hook_env,
        )
        if result is not None:
            report.check(
                "self-test stop respects stop_hook_active",
                not (result.stdout or "").strip(),
                f"stdout={result.stdout!r}",
            )


def _run_hook(
    script: Path,
    payload: str,
    cwd: Path,
    env: dict | None = None,
) -> subprocess.CompletedProcess | None:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    try:
        return subprocess.run(
            [sys.executable, str(script)],
            input=payload,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            env=merged,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _try_git_init(path: Path) -> bool:
    result = _git(path, ["init"])
    return result is not None and result.returncode == 0


def _git(path: Path, args: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project = Path(args.project).expanduser()
    if not project.is_dir():
        print(f"error: --project is not a directory: {project}", file=sys.stderr)
        return EXIT_ERROR
    project = project.resolve()

    raw = args.codex_home or os.environ.get("CODEX_HOME")
    if not raw:
        print(
            "error: no Codex home given. Pass --codex-home PATH or set CODEX_HOME.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    codex_home = Path(raw).expanduser()

    report = Report()
    check_layout(project, codex_home, report)
    if args.self_test:
        hook_self_test(project, report)

    if args.json:
        print(
            json.dumps(
                {
                    "project": str(project),
                    "codex_home": str(codex_home),
                    "checks": [
                        {"status": status, "name": name, "detail": detail}
                        for status, name, detail in report.checks
                    ],
                    "errors": report.errors,
                    "warnings": report.warnings,
                },
                indent=2,
            )
        )
    else:
        width = max((len(name) for _, name, _ in report.checks), default=10)
        for status, name, detail in report.checks:
            line = f"[{status:<5}] {name:<{width}}  {detail}".rstrip()
            print(line)
        print("")
        print(f"errors: {len(report.errors)}   warnings: {len(report.warnings)}")

    return EXIT_FAIL if report.errors else EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
