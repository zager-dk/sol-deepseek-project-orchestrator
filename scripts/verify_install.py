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
import shutil
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Optional

try:
    import tomllib
except ImportError:  # Python < 3.11: never replace a parser with a scanner.
    tomllib = None

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "sol-deepseek-project-orchestrator"
ROLE_AGENTS = {
    "luna-worker.toml": ("luna_worker", "gpt-6-luna", "medium"),
    "luna-reviewer.toml": ("luna_reviewer", "gpt-6-luna", "high"),
    "sol-senior.toml": ("sol_senior", "gpt-6.1-sol", "high"),
    "sol-reviewer.toml": ("sol_reviewer", "gpt-6.1-sol", "high"),
    "astra-consultant.toml": ("astra_consultant", "gpt-6-astra", "high"),
    "luna-state-editor.toml": ("luna_state_editor", "gpt-6-luna", "low"),
}
ROOT_PROFILE_NAME = "orchestrator-director.config.toml"
MANIFEST_NAME = "orchestrator-install-manifest.json"
ROLE_SANDBOX = {
    "luna-worker.toml": None,
    "luna-reviewer.toml": None,
    "luna-state-editor.toml": None,
    "sol-senior.toml": None,
    "sol-reviewer.toml": "read-only",
    "astra-consultant.toml": None,
}

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


def read_toml_config(path: Path, label: str, report: Report) -> Optional[dict]:
    """Parse real TOML strictly; unreadable/invalid configs cannot be accepted."""
    if tomllib is None:
        report.check(f"{label} TOML parser", False,
                     "TOML parser unavailable; rerun verification with Python 3.11+ (stdlib tomllib); no configuration was validated")
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        report.check(f"{label} TOML parses", False, f"cannot read/parse {path}: {exc}")
        return None
    report.check(f"{label} TOML parses", True, str(path))
    return data


def check_config_contract(data: dict, contract: dict, label: str, report: Report) -> None:
    for (table, key), expected in contract.items():
        values = data.get(table, {}) if table else data
        actual = values.get(key) if isinstance(values, dict) else None
        matches = (isinstance(values, dict) and key not in values) if expected is None else (
            type(actual) is type(expected) and actual == expected)
        report.check(f"{label} {table + '.' if table else ''}{key}", matches,
                     f"expected configured value {expected if expected is not None else '<unset>'!r}; service_tier is a request and does not prove runtime execution tier")


def parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
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
    parser.add_argument("--no-agent", action="store_true",
                        help="explicitly allow absent child-role files after install --no-agent; existing roles are always verified")
    return parser.parse_args(argv)


def check_layout(project: Path, codex_home: Path, report: Report, *, no_agent: bool = False) -> None:
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
    report.check(
        "skill runtime helper",
        (skill_dir / "scripts" / "orchestrate.py").is_file(),
        str(skill_dir / "scripts" / "orchestrate.py"),
    )
    for reference in ("DELEGATION_CONTRACT.md", "STATE_POLICY.md", "ROUTING.md"):
        path = skill_dir / "references" / reference
        report.check(f"skill reference {reference}", path.is_file(), str(path))

    root_profile = codex_home / ROOT_PROFILE_NAME
    report.check("director root profile present", root_profile.is_file(), str(root_profile))
    if root_profile.is_file():
        profile = read_toml_config(root_profile, "director profile", report)
        root_contract = {
            ("", "model"): "gpt-6.1-sol",
            ("", "model_reasoning_effort"): "high",
            ("", "service_tier"): "standard",
            ("agents", "enabled"): True,
            ("agents", "max_concurrent_threads_per_session"): 4,
        }
        if profile is not None:
            check_config_contract(profile, root_contract, "director profile", report)

    # Ownership manifests say who may remove a file, not whether its installed
    # configuration needs verification or whether --no-agent was requested.
    for filename, (role, model, effort) in ROLE_AGENTS.items():
        agent = codex_home / "agents" / filename
        try:
            agent.lstat()
        except FileNotFoundError:
            if no_agent:
                report.warn(f"agent {role} absent", "explicit verifier --no-agent allows missing roles; this role configuration was not verified")
            else:
                report.check(f"agent {role} present", False,
                             f"{agent}; for an intentional install --no-agent, verify with --no-agent too")
            continue
        except OSError as exc:
            report.check(f"agent {role} present", False, f"cannot inspect {agent}: {exc}")
            continue
        report.check(f"agent {role} present", True, str(agent))
        data = read_toml_config(agent, f"agent {role}", report)
        contract = {
            ("", "name"): role,
            ("", "model"): model,
            ("", "model_reasoning_effort"): effort,
            ("", "service_tier"): "standard",
            ("", "sandbox_mode"): ROLE_SANDBOX[filename],
            ("agents", "enabled"): False,
        }
        if data is not None:
            check_config_contract(data, contract, f"agent {role}", report)

    legacy = codex_home / "agents" / "deepseek-worker.toml"
    if legacy.is_file():
        legacy_text = legacy.read_text(encoding="utf-8", errors="replace").lower()
        if "deepseek" in legacy_text:
            report.warn(
                "legacy agent routing",
                f"{legacy} is an existing legacy definition and still names DeepSeek; it was not changed",
            )
    agents_dir = codex_home / "agents"
    if agents_dir.is_dir():
        for candidate in sorted(agents_dir.glob("*.toml")):
            if candidate == legacy or candidate.name in ROLE_AGENTS:
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace").lower()
            if "astra_flash_builder" in text and "deepseek" in text:
                report.warn(
                    "legacy Astra alias",
                    f"{candidate} combines astra_flash_builder with DeepSeek routing; preserved without changes",
                )

    report.warn(
        "model execution",
        "verification checks configured model and effort values only; it does not invoke agents or prove runtime availability",
    )

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
        report.check(
            "hooks runtime helper",
            (project / ".codex" / "hooks" / "orchestrate.py").is_file(),
            str(project / ".codex" / "hooks" / "orchestrate.py"),
        )
        for event, groups in events.items():
            for group in groups if isinstance(groups, list) else []:
                for handler in group.get("hooks", []):
                    command = handler.get("command")
                    if not isinstance(command, str):
                        continue
                    candidate, parse_error = hook_script_operand(command, event)
                    script_exists = bool(candidate) and Path(candidate).is_file()
                    report.check(
                        f"{event} hook script exists",
                        script_exists,
                        candidate if candidate else parse_error,
                    )
                    windows = handler.get("commandWindows")
                    if windows is not None:
                        safe = isinstance(windows, str) and windows.startswith(
                            "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
                        )
                        report.check(f"{event} Windows hook command is encoded", safe, "expected base64 PowerShell invocation")
    else:
        report.warn("project hooks", f"no {hooks_json}; run install.py --hooks to add them")


def hook_script_operand(command: str, event: str) -> tuple[Optional[str], str]:
    """Parse only installer-shaped Python hook commands; never execute them."""
    expected_scripts = {
        "SessionStart": "inject_project_state.py",
        "Stop": "stop_project_state_check.py",
    }
    expected = expected_scripts.get(event)
    if expected is None:
        return None, f"unsupported hook event {event!r}"
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as exc:
        return None, f"invalid quoted command: {exc}"
    if len(argv) not in (2, 4) or (len(argv) == 4 and argv[2] != "--data-dir"):
        return None, "unsupported command shape"
    if len(argv) == 4 and not argv[3]:
        return None, "empty --data-dir value"
    executable_name = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    executable_stem = executable_name[:-4] if executable_name.endswith(".exe") else executable_name
    versioned_python = executable_stem == "python3" or (executable_stem.startswith("python3") and executable_stem[7:].replace(".", "").isdigit())
    if executable_stem not in {"python", "py"} and not versioned_python:
        return None, "unsupported Python interpreter operand"
    script = argv[1]
    script_name = script.replace("\\", "/").rsplit("/", 1)[-1]
    if script_name != expected:
        return None, f"expected {expected} as script operand"
    return script, ""


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
        helper_source = hooks_dir / "orchestrate.py"
        if helper_source.is_file():
            (state_dir / "hooks").mkdir(parents=True, exist_ok=True)
            shutil.copy2(helper_source, state_dir / "hooks" / "orchestrate.py")
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

        if not git_ok:
            report.warn("self-test", "git unavailable; skipped the change-detection check")
            return

        tracked = sandbox / "app.txt"
        tracked.write_text("v1\n", encoding="utf-8")
        _git(sandbox, ["add", "-A"])
        _git(sandbox, ["-c", "user.email=verify@example.invalid", "-c", "user.name=verify", "commit", "-m", "init"])
        helper = state_dir / "hooks" / "orchestrate.py"
        if helper.is_file():
            snapshot = subprocess.run(
                [sys.executable, str(helper), "--project", str(sandbox), "snapshot", "--json"],
                cwd=str(sandbox), capture_output=True, text=True, timeout=60, check=False,
            )
            try:
                fingerprint = json.loads(snapshot.stdout)["state_fingerprint"] if snapshot.returncode == 0 else None
            except (ValueError, KeyError, TypeError):
                fingerprint = None
            if fingerprint:
                with (state_dir / "PROJECT_STATE.md").open("a", encoding="utf-8") as stream:
                    stream.write(f"\n<!-- orchestrator-snapshot:{fingerprint} -->\n")
        result = _run_hook(
            stop,
            json.dumps({"cwd": str(sandbox), "turn_id": f"verify-clean-{uuid.uuid4()}"}),
            sandbox,
            env=hook_env,
        )
        if result is None:
            report.check("self-test stop runs", False, "process did not start")
            return
        report.check(
            "self-test stop silent on a current snapshot",
            not (result.stdout or "").strip(),
            f"stdout={result.stdout!r}",
        )
        tracked.write_text("v2\n", encoding="utf-8")
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
    env: Optional[dict] = None,
) -> Optional[subprocess.CompletedProcess]:
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


def _git(path: Path, args: list[str]) -> Optional[subprocess.CompletedProcess]:
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


def main(argv: Optional[list[str]] = None) -> int:
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
    check_layout(project, codex_home, report, no_agent=args.no_agent)
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
