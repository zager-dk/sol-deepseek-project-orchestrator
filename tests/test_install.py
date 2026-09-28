#!/usr/bin/env python3
"""Non-destructive tests for the installer, hooks, verifier, and uninstaller.

Run from the repository root:

    python -m unittest discover -s tests -v

Every test works inside a temporary directory. Nothing here touches a real
Codex home, a real project, or the network.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL = REPO_ROOT / "scripts" / "install.py"
UNINSTALL = REPO_ROOT / "scripts" / "uninstall.py"
VERIFY = REPO_ROOT / "scripts" / "verify_install.py"
INJECT_HOOK = REPO_ROOT / "hooks" / "inject_project_state.py"
STOP_HOOK = REPO_ROOT / "hooks" / "stop_project_state_check.py"
SKILL_NAME = "sol-deepseek-project-orchestrator"

GIT_AVAILABLE = shutil.which("git") is not None


def run(cmd: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("CODEX_HOME", None)
    if env:
        merged.update(env)
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=merged,
        timeout=180,
        check=False,
    )


def run_hook(
    script: Path, payload: dict, *, cwd: Path, env: dict | None = None
) -> subprocess.CompletedProcess:
    merged = os.environ.copy()
    merged.pop("SOL_DEEPSEEK_DISABLE_STATE_HOOK", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(cwd),
        env=merged,
        timeout=60,
        check=False,
    )


def git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return run(["git", *args], cwd=path)


class TempRepoCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="sdo-test-")
        self.tmp = Path(self._tmp.name)
        self.codex_home = self.tmp / "codexhome"
        self.codex_home.mkdir()
        (self.codex_home / "config.toml").write_text("# fake home\n", encoding="utf-8")
        self.project = self.tmp / "project"
        self.project.mkdir()
        if GIT_AVAILABLE:
            git(self.project, "init")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def install(self, *extra: str, codex_home: Path | None = None, project: Path | None = None, env: dict | None = None):
        return run(
            [
                sys.executable,
                str(INSTALL),
                "--project",
                str(project or self.project),
                "--codex-home",
                str(codex_home or self.codex_home),
                *extra,
            ],
            cwd=REPO_ROOT,
            env=env,
        )

    @property
    def skill_dir(self) -> Path:
        return self.codex_home / "skills" / SKILL_NAME


class InstallTests(TempRepoCase):
    def test_fresh_install_creates_expected_files(self) -> None:
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        self.assertTrue((self.skill_dir / "SKILL.md").is_file())
        self.assertTrue((self.skill_dir / "ARCHITECTURE.md").is_file())
        for reference in ("DELEGATION_CONTRACT.md", "STATE_POLICY.md", "ROUTING.md"):
            self.assertTrue((self.skill_dir / "references" / reference).is_file())
        self.assertTrue((self.codex_home / "agents" / "deepseek-worker.toml").is_file())
        self.assertTrue((self.project / ".codex" / "PROJECT_STATE.md").is_file())
        self.assertFalse((self.project / ".codex" / "hooks.json").exists())
        self.assertFalse((self.project / "AGENTS.md").exists())

    def test_installed_skill_matches_bundled_skill(self) -> None:
        self.install()
        bundled = (REPO_ROOT / "skill" / "SKILL.md").read_bytes()
        self.assertEqual((self.skill_dir / "SKILL.md").read_bytes(), bundled)

    def test_repeat_install_is_idempotent(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self.install()
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("created   : 0", second.stdout)
        self.assertIn("updated   : 0", second.stdout)
        self.assertGreater(int(second.stdout.split("unchanged : ")[1].splitlines()[0]), 0)
        backups = list(self.codex_home.rglob("*.bak"))
        self.assertEqual(backups, [])

    def test_conflict_without_force_exits_three_and_writes_nothing(self) -> None:
        self.skill_dir.mkdir(parents=True)
        (self.skill_dir / "SKILL.md").write_text("user content\n", encoding="utf-8")

        result = self.install()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertIn("Nothing was written", result.stdout)
        self.assertEqual(
            (self.skill_dir / "SKILL.md").read_text(encoding="utf-8"), "user content\n"
        )
        self.assertFalse((self.codex_home / "agents" / "deepseek-worker.toml").exists())
        self.assertFalse((self.project / ".codex" / "PROJECT_STATE.md").exists())

    def test_force_replaces_managed_file_and_keeps_backup(self) -> None:
        self.skill_dir.mkdir(parents=True)
        (self.skill_dir / "SKILL.md").write_text("user content\n", encoding="utf-8")

        result = self.install("--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            (self.skill_dir / "SKILL.md").read_bytes(),
            (REPO_ROOT / "skill" / "SKILL.md").read_bytes(),
        )
        backup = self.skill_dir / "SKILL.md.bak"
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding="utf-8"), "user content\n")

    def test_project_state_is_never_overwritten(self) -> None:
        state = self.project / ".codex" / "PROJECT_STATE.md"
        state.parent.mkdir(parents=True)
        state.write_text("# my own state\n", encoding="utf-8")

        result = self.install("--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(state.read_text(encoding="utf-8"), "# my own state\n")
        self.assertIn("preserved : 1", result.stdout)

    def test_agents_md_is_opt_in_and_user_owned(self) -> None:
        existing = self.project / "AGENTS.md"
        existing.write_text("# user agents\n", encoding="utf-8")

        result = self.install("--agents-md", "--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(existing.read_text(encoding="utf-8"), "# user agents\n")

        other = self.tmp / "project2"
        other.mkdir()
        result = self.install("--agents-md", project=other)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((other / "AGENTS.md").is_file())

    def test_dry_run_writes_nothing(self) -> None:
        result = self.install("--hooks", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Dry run", result.stdout)
        self.assertFalse(self.skill_dir.exists())
        self.assertFalse((self.project / ".codex").exists())

    def test_missing_codex_home_is_a_usage_error(self) -> None:
        result = run(
            [sys.executable, str(INSTALL), "--project", str(self.project)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("CODEX_HOME", result.stderr)

    def test_codex_home_env_variable_is_used(self) -> None:
        result = run(
            [sys.executable, str(INSTALL), "--project", str(self.project)],
            cwd=REPO_ROOT,
            env={"CODEX_HOME": str(self.codex_home)},
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.skill_dir / "SKILL.md").is_file())

    def test_missing_project_is_a_usage_error(self) -> None:
        result = self.install(project=self.tmp / "nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)

    def test_no_agent_flag_skips_the_agent_file(self) -> None:
        result = self.install("--no-agent")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.codex_home / "agents" / "deepseek-worker.toml").exists())

    def test_prune_removes_stale_skill_files(self) -> None:
        self.install()
        stale = self.skill_dir / "references" / "OLD.md"
        stale.write_text("stale\n", encoding="utf-8")

        result = self.install("--prune")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(stale.exists())
        self.assertTrue((self.skill_dir / "SKILL.md").is_file())

    def test_json_output_is_machine_readable(self) -> None:
        result = self.install("--json", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "planned")
        self.assertGreater(len(payload["actions"]), 0)

    def test_warns_when_project_is_not_a_git_repository(self) -> None:
        plain = self.tmp / "plain"
        plain.mkdir()
        result = self.install(project=plain)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("does not look like a git repository", result.stdout)


class HookInstallTests(TempRepoCase):
    def test_hooks_install_writes_valid_config_and_scripts(self) -> None:
        result = self.install("--hooks")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        hooks_dir = self.project / ".codex" / "hooks"
        self.assertTrue((hooks_dir / "inject_project_state.py").is_file())
        self.assertTrue((hooks_dir / "stop_project_state_check.py").is_file())

        config = json.loads(
            (self.project / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        events = config["hooks"]
        self.assertEqual(
            set(events),
            {"SessionStart", "Stop"},
        )
        # PostCompact only supports the common output fields, so the state
        # injector must not be registered there.
        self.assertNotIn("PostCompact", events)
        self.assertEqual(
            events["SessionStart"][0]["matcher"], "startup|resume|clear|compact"
        )
        for event, groups in events.items():
            for group in groups:
                for handler in group["hooks"]:
                    self.assertEqual(handler["type"], "command")
                    self.assertIn(self.project.as_posix(), handler["command"])
                    script = handler["command"].split('"')[1]
                    self.assertTrue(Path(script).is_file(), script)
                    # JSON keys are camelCase; snake_case is TOML-only.
                    self.assertNotIn("command_windows", handler)
                    if "commandWindows" in handler:
                        windows_script = handler["commandWindows"].split('"')[1]
                        self.assertTrue(Path(windows_script).is_file(), windows_script)

    def test_bundled_hooks_example_matches_the_generated_shape(self) -> None:
        self.install("--hooks")
        generated = json.loads(
            (self.project / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        example = json.loads(
            (REPO_ROOT / "templates" / "hooks.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(generated["hooks"]), set(example["hooks"]))
        self.assertEqual(
            generated["hooks"]["SessionStart"][0]["matcher"],
            example["hooks"]["SessionStart"][0]["matcher"],
        )

        def handler_keys(node, found):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "type" and value == "command":
                        found.append(set(node))
                    handler_keys(value, found)
            elif isinstance(node, list):
                for item in node:
                    handler_keys(item, found)

        generated_keys: list[set] = []
        example_keys: list[set] = []
        handler_keys(generated, generated_keys)
        handler_keys(example, example_keys)
        self.assertEqual(len(generated_keys), len(example_keys))
        for generated_set, example_set in zip(generated_keys, example_keys):
            # The example always shows the Windows override; a POSIX install
            # does not emit it at all. Nothing else may differ.
            self.assertTrue(
                generated_set.issubset(example_set),
                f"{sorted(generated_set)} not a subset of {sorted(example_set)}",
            )
            self.assertLessEqual(example_set - generated_set, {"commandWindows"})
        for keys in example_keys:
            self.assertNotIn("command_windows", keys)

    def test_hooks_config_is_stable_across_installs(self) -> None:
        self.install("--hooks")
        first = (self.project / ".codex" / "hooks.json").read_bytes()
        result = self.install("--hooks")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.project / ".codex" / "hooks.json").read_bytes(), first)
        self.assertIn("created   : 0", result.stdout)

    def test_repeated_install_with_hooks_reports_conflict_when_edited(self) -> None:
        self.install("--hooks")
        hooks_json = self.project / ".codex" / "hooks.json"
        hooks_json.write_text('{"hooks": {}}\n', encoding="utf-8")
        result = self.install("--hooks")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(
            hooks_json.read_text(encoding="utf-8"), '{"hooks": {}}\n'
        )


class InjectHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="sdo-inject-")
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_state(self, text: str, where: Path | None = None) -> Path:
        base = where or self.root
        state = base / ".codex" / "PROJECT_STATE.md"
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(text, encoding="utf-8")
        return state

    def test_silent_when_no_state_file_exists(self) -> None:
        result = run_hook(
            INJECT_HOOK, {"hook_event_name": "SessionStart", "cwd": str(self.root)}, cwd=self.root
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_returns_state_as_additional_context(self) -> None:
        self.write_state("# Project State\n\n## Project intent\nship the thing\n")
        result = run_hook(
            INJECT_HOOK, {"hook_event_name": "SessionStart", "cwd": str(self.root)}, cwd=self.root
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(
            payload["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )
        self.assertIn("ship the thing", payload["hookSpecificOutput"]["additionalContext"])

    def test_finds_state_from_a_subdirectory(self) -> None:
        self.write_state("# Project State\n\n## Project intent\nnested lookup\n")
        nested = self.root / "src" / "deep"
        nested.mkdir(parents=True)
        result = run_hook(
            INJECT_HOOK, {"hook_event_name": "SessionStart", "cwd": str(nested)}, cwd=nested
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("nested lookup", result.stdout)

    def test_truncates_oversized_state(self) -> None:
        self.write_state("# Project State\n\n" + ("x" * 8000) + "\n")
        result = run_hook(
            INJECT_HOOK,
            {"hook_event_name": "SessionStart", "cwd": str(self.root)},
            cwd=self.root,
            env={"SOL_DEEPSEEK_STATE_MAX_BYTES": "2000"},
        )
        self.assertEqual(result.returncode, 0)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("truncated by inject_project_state.py", context)
        self.assertLess(len(context), 6000)

    def test_disable_env_var_suppresses_output(self) -> None:
        self.write_state("# Project State\n\n## Project intent\nsecret\n")
        result = run_hook(
            INJECT_HOOK,
            {"hook_event_name": "SessionStart", "cwd": str(self.root)},
            cwd=self.root,
            env={"SOL_DEEPSEEK_DISABLE_STATE_HOOK": "1"},
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_stdout_stays_clean_on_broken_stdin(self) -> None:
        self.write_state("# Project State\n\n## Project intent\nstill fine\n")
        result = subprocess.run(
            [sys.executable, str(INJECT_HOOK)],
            input="not json at all",
            capture_output=True,
            text=True,
            cwd=str(self.root),
            timeout=60,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        json.loads(result.stdout)


@unittest.skipUnless(GIT_AVAILABLE, "git is required for the Stop hook tests")
class StopHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="sdo-stop-")
        self.tmp = Path(self._tmp.name)
        # Keep the repository in a subdirectory so "outside the repository"
        # actually means outside: git walks up to the nearest repository.
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.nudge_dir = self.tmp / "nudge-markers"
        git(self.root, "init")
        git(self.root, "config", "user.email", "test@example.invalid")
        git(self.root, "config", "user.name", "test")
        self.state = self.root / ".codex" / "PROJECT_STATE.md"
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text("# Project State\n", encoding="utf-8")
        self.tracked = self.root / "app.txt"
        self.tracked.write_text("v1\n", encoding="utf-8")
        git(self.root, "add", "-A")
        commit = git(self.root, "commit", "-m", "init")
        if commit.returncode != 0:
            self.skipTest(f"git commit unavailable: {commit.stderr}")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def hook(self, payload: dict) -> subprocess.CompletedProcess:
        merged = {"SOL_DEEPSEEK_NUDGE_DIR": str(self.nudge_dir)}
        return run_hook(STOP_HOOK, payload, cwd=self.root, env=merged)

    def test_silent_on_a_clean_tree(self) -> None:
        result = self.hook({"cwd": str(self.root), "turn_id": "t1"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_silent_when_state_is_newer_than_changes(self) -> None:
        self.tracked.write_text("v2\n", encoding="utf-8")
        now = 2_000_000_000
        os.utime(self.tracked, (now, now))
        os.utime(self.state, (now + 60, now + 60))
        result = self.hook({"cwd": str(self.root), "turn_id": "t2"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_nudges_once_when_state_is_stale(self) -> None:
        self.tracked.write_text("v3\n", encoding="utf-8")
        os.utime(self.tracked, (2_000_000_000, 2_000_000_000))
        os.utime(self.state, (1_000_000_000, 1_000_000_000))

        result = self.hook({"cwd": str(self.root), "turn_id": "t3"})
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("PROJECT_STATE.md", payload["reason"])

        again = self.hook({"cwd": str(self.root), "turn_id": "t3"})
        self.assertEqual(again.stdout.strip(), "")

    def test_respects_stop_hook_active(self) -> None:
        self.tracked.write_text("v4\n", encoding="utf-8")
        os.utime(self.tracked, (2_000_000_000, 2_000_000_000))
        os.utime(self.state, (1_000_000_000, 1_000_000_000))
        result = self.hook(
            {"cwd": str(self.root), "turn_id": "t4", "stop_hook_active": True}
        )
        self.assertEqual(result.stdout.strip(), "")

    def test_nudges_when_state_file_is_missing(self) -> None:
        self.state.unlink()
        # Keep .codex non-empty so the directory still shows up in git status.
        (self.root / ".codex" / "notes.txt").write_text("x\n", encoding="utf-8")
        os.utime(self.root / ".codex" / "notes.txt", (2_000_000_000, 2_000_000_000))
        result = self.hook({"cwd": str(self.root), "turn_id": "t5"})
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("no", payload["reason"].lower())

    def test_silent_outside_a_git_repository(self) -> None:
        plain = self.tmp / "not-a-repo"
        plain.mkdir()
        (plain / "file.txt").write_text("x\n", encoding="utf-8")
        result = run_hook(STOP_HOOK, {"cwd": str(plain), "turn_id": "t6"}, cwd=plain)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_disable_env_var_suppresses_output(self) -> None:
        self.tracked.write_text("v5\n", encoding="utf-8")
        os.utime(self.tracked, (2_000_000_000, 2_000_000_000))
        os.utime(self.state, (1_000_000_000, 1_000_000_000))
        result = run_hook(
            STOP_HOOK,
            {"cwd": str(self.root), "turn_id": "t7"},
            cwd=self.root,
            env={
                "SOL_DEEPSEEK_DISABLE_STATE_HOOK": "1",
                "SOL_DEEPSEEK_NUDGE_DIR": str(self.nudge_dir),
            },
        )
        self.assertEqual(result.stdout.strip(), "")


class UninstallTests(TempRepoCase):
    def test_uninstall_removes_managed_files_and_keeps_state(self) -> None:
        self.install("--hooks", "--agents-md")
        state = self.project / ".codex" / "PROJECT_STATE.md"
        self.assertTrue(state.is_file())

        result = run(
            [
                sys.executable,
                str(UNINSTALL),
                "--project",
                str(self.project),
                "--codex-home",
                str(self.codex_home),
            ],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.skill_dir.exists())
        self.assertFalse((self.codex_home / "agents" / "deepseek-worker.toml").exists())
        self.assertFalse((self.project / ".codex" / "hooks.json").exists())
        self.assertTrue(state.is_file())
        self.assertTrue((self.project / "AGENTS.md").is_file())

    def test_uninstall_keeps_handwritten_hooks_json(self) -> None:
        (self.project / ".codex").mkdir(parents=True)
        handwritten = self.project / ".codex" / "hooks.json"
        handwritten.write_text('{"hooks": {"Stop": []}}\n', encoding="utf-8")

        result = run(
            [
                sys.executable,
                str(UNINSTALL),
                "--project",
                str(self.project),
                "--codex-home",
                str(self.codex_home),
            ],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(handwritten.is_file())
        self.assertIn("kept", result.stdout)

    def test_purge_state_removes_the_state_file(self) -> None:
        self.install()
        result = run(
            [
                sys.executable,
                str(UNINSTALL),
                "--project",
                str(self.project),
                "--codex-home",
                str(self.codex_home),
                "--purge-state",
            ],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.project / ".codex" / "PROJECT_STATE.md").exists())


class VerifyInstallTests(TempRepoCase):
    def verify(self, *extra: str) -> subprocess.CompletedProcess:
        return run(
            [
                sys.executable,
                str(VERIFY),
                "--project",
                str(self.project),
                "--codex-home",
                str(self.codex_home),
                *extra,
            ],
            cwd=REPO_ROOT,
        )

    def test_verify_passes_on_a_good_install(self) -> None:
        self.install("--hooks")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("errors: 0", result.stdout)

    def test_verify_self_test_exercises_the_hooks(self) -> None:
        self.install("--hooks")
        result = self.verify("--self-test")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("self-test inject returns state context", result.stdout)
        if GIT_AVAILABLE:
            self.assertIn("self-test stop nudges on a stale state file", result.stdout)

    def test_verify_fails_when_the_skill_is_missing(self) -> None:
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("skill SKILL.md", result.stdout)

    def test_verify_json_output(self) -> None:
        self.install()
        result = self.verify("--json")
        payload = json.loads(result.stdout)
        self.assertEqual(payload["errors"], [])


@unittest.skipUnless(GIT_AVAILABLE, "git is required for the end-to-end test")
class EndToEndTests(unittest.TestCase):
    """Fresh throwaway repository: install, hook behavior, verify, uninstall."""

    def test_full_cycle_on_a_fresh_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdo-e2e-") as raw:
            tmp = Path(raw)
            project = tmp / "fresh-repo"
            project.mkdir()
            codex_home = tmp / "codexhome"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text("# fake home\n", encoding="utf-8")

            self.assertEqual(git(project, "init").returncode, 0)

            install = run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--project",
                    str(project),
                    "--codex-home",
                    str(codex_home),
                    "--hooks",
                    "--agents-md",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)

            verify = run(
                [
                    sys.executable,
                    str(VERIFY),
                    "--project",
                    str(project),
                    "--codex-home",
                    str(codex_home),
                    "--self-test",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(verify.returncode, 0, verify.stdout + verify.stderr)

            installed_inject = project / ".codex" / "hooks" / "inject_project_state.py"
            payload = json.dumps(
                {"hook_event_name": "SessionStart", "cwd": str(project)}
            )
            hook_result = subprocess.run(
                [sys.executable, str(installed_inject)],
                input=payload,
                capture_output=True,
                text=True,
                cwd=str(project),
                timeout=60,
                check=False,
            )
            self.assertEqual(hook_result.returncode, 0, hook_result.stderr)
            context = json.loads(hook_result.stdout)["hookSpecificOutput"][
                "additionalContext"
            ]
            self.assertIn("Project State", context)

            second = run(
                [
                    sys.executable,
                    str(INSTALL),
                    "--project",
                    str(project),
                    "--codex-home",
                    str(codex_home),
                    "--hooks",
                    "--agents-md",
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertIn("created   : 0", second.stdout)

            uninstall = run(
                [
                    sys.executable,
                    str(UNINSTALL),
                    "--project",
                    str(project),
                    "--codex-home",
                    str(codex_home),
                ],
                cwd=REPO_ROOT,
            )
            self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
            self.assertTrue((project / ".codex" / "PROJECT_STATE.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
