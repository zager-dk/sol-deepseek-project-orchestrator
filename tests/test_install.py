#!/usr/bin/env python3
"""Non-destructive tests for the installer, hooks, verifier, and uninstaller.

Run from the repository root:

    python -m unittest discover -s tests -v

Every test works inside a temporary directory. Nothing here touches a real
Codex home, a real project, or the network.
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
try:
    import tomllib
except ImportError:
    tomllib = None
from pathlib import Path
from typing import Optional
from test_support import cleanup_temporary_directory

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL = REPO_ROOT / "scripts" / "install.py"
UNINSTALL = REPO_ROOT / "scripts" / "uninstall.py"
VERIFY = REPO_ROOT / "scripts" / "verify_install.py"
INJECT_HOOK = REPO_ROOT / "hooks" / "inject_project_state.py"
STOP_HOOK = REPO_ROOT / "hooks" / "stop_project_state_check.py"
SKILL_NAME = "sol-deepseek-project-orchestrator"

GIT_AVAILABLE = shutil.which("git") is not None


def isolated_env(root: Path, extra: Optional[dict] = None) -> dict[str, str]:
    """Keep child processes away from user Codex, Git, and signing config."""
    home = root / "test-user-home"
    home.mkdir(parents=True, exist_ok=True)
    git_config = root / "test-gitconfig"
    if not git_config.exists():
        git_config.write_text("", encoding="utf-8")
    keep = ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "TEMP", "TMP", "GIT_CEILING_DIRECTORIES")
    merged = {key: os.environ[key] for key in keep if key in os.environ}
    merged.update({
        "HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(home / "AppData" / "Roaming"),
        "LOCALAPPDATA": str(home / "AppData" / "Local"), "GIT_CONFIG_GLOBAL": str(git_config),
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_COUNT": "0", "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    if extra:
        merged.update(extra)
    return merged


def run(cmd: list[str], *, cwd: Path, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="sdo-child-home-") as raw:
        merged = isolated_env(Path(raw), env)
        return subprocess.run(
            cmd, cwd=str(cwd), capture_output=True, text=True, encoding="utf-8",
            env=merged, timeout=180, check=False,
        )


def run_hook(
    script: Path, payload: dict, *, cwd: Path, env: Optional[dict] = None
) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory(prefix="sdo-hook-home-") as raw:
        merged = isolated_env(Path(raw), env)
        return subprocess.run(
            [sys.executable, str(script)], input=json.dumps(payload), capture_output=True,
            text=True, encoding="utf-8", cwd=str(cwd), env=merged, timeout=60, check=False,
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
        cleanup_temporary_directory(self._tmp)

    def install(self, *extra: str, codex_home: Optional[Path] = None, project: Optional[Path] = None, env: Optional[dict] = None):
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

    def write_manifest(self, files: dict[str, str]) -> Path:
        manifest_path = self.project / ".codex" / "orchestrator-install-manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = {"version": 1, "files": files}
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest_path

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
        self.assertTrue((self.codex_home / "orchestrator-director.config.toml").is_file())
        for name in ("luna-worker.toml", "luna-reviewer.toml", "sol-senior.toml", "sol-reviewer.toml", "astra-consultant.toml", "luna-state-editor.toml"):
            self.assertTrue((self.codex_home / "agents" / name).is_file())
        self.assertTrue((self.skill_dir / "scripts" / "orchestrate.py").is_file())
        self.assertTrue((self.project / ".codex" / "orchestrator-install-manifest.json").is_file())
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
        self.assertFalse((self.codex_home / "agents" / "luna-worker.toml").exists())
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

    def test_force_preserves_existing_temp_and_backup_sentinels(self) -> None:
        self.skill_dir.mkdir(parents=True)
        target = self.skill_dir / "SKILL.md"
        target.write_text("user content\n", encoding="utf-8")
        temporary = target.with_name(target.name + ".tmp-install")
        prior_backup = target.with_name(target.name + ".bak")
        temporary.write_text("temporary sentinel\n", encoding="utf-8")
        prior_backup.write_text("older backup sentinel\n", encoding="utf-8")
        result = self.install("--force")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(temporary.read_text(encoding="utf-8"), "temporary sentinel\n")
        self.assertEqual(prior_backup.read_text(encoding="utf-8"), "older backup sentinel\n")
        next_backup = target.with_name(target.name + ".bak.1")
        self.assertEqual(next_backup.read_text(encoding="utf-8"), "user content\n")

    def test_project_hooks_json_conflict_cannot_be_forced(self) -> None:
        hooks_json = self.project / ".codex" / "hooks.json"
        hooks_json.parent.mkdir(parents=True)
        sentinel = '{"hooks":{"Stop":[]}}\n'
        hooks_json.write_text(sentinel, encoding="utf-8")
        result = self.install("--hooks", "--force")
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(hooks_json.read_text(encoding="utf-8"), sentinel)
        self.assertFalse((self.project / ".codex" / "hooks" / "orchestrate.py").exists())

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

    def test_create_does_not_clobber_legacy_temp_filename(self) -> None:
        self.skill_dir.mkdir(parents=True)
        legacy_temp = self.skill_dir / "SKILL.md.tmp-install"
        legacy_temp.write_text("user temp sentinel\n", encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.skill_dir / "SKILL.md").is_file())
        self.assertEqual(legacy_temp.read_text(encoding="utf-8"), "user temp sentinel\n")

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
        self.assertFalse((self.codex_home / "agents" / "luna-worker.toml").exists())
        self.assertTrue((self.codex_home / "orchestrator-director.config.toml").is_file())

    def test_prune_preserves_untracked_skill_files(self) -> None:
        self.install()
        stale = self.skill_dir / "references" / "OLD.md"
        stale.write_text("stale\n", encoding="utf-8")

        result = self.install("--prune")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(stale.exists())
        self.assertTrue((self.skill_dir / "SKILL.md").is_file())

    def test_force_prune_ignores_checksummed_claim_to_user_skill_file(self) -> None:
        first = self.install()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        custom = self.skill_dir / "user-custom.md"
        sentinel = b"USER sentinel\n"
        custom.write_bytes(sentinel)
        manifest_path = self.write_manifest({str(custom.resolve()): hashlib.sha256(sentinel).hexdigest()})

        result = self.install("--force", "--prune")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(custom.read_bytes(), sentinel)
        self.assertNotIn(str(custom.resolve()), json.loads(manifest_path.read_text(encoding="utf-8"))["files"])
        self.assertIn("exact managed-file allowlist", result.stdout)
        uninstall = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(uninstall.returncode, 0, uninstall.stdout + uninstall.stderr)
        self.assertEqual(custom.read_bytes(), sentinel)

    def test_prune_removes_known_retired_file_and_preserves_modified_retired_file(self) -> None:
        # Simulate a later bundle dropping a recognized optional skill document.
        # The exact architecture path remains allowlisted without a source file.
        bundle = self.tmp / "later-bundle"
        (bundle / "scripts").mkdir(parents=True)
        for name in ("install.py", "orchestrate.py"):
            shutil.copy2(REPO_ROOT / "scripts" / name, bundle / "scripts" / name)
        for name in ("skill", "templates", "hooks"):
            shutil.copytree(REPO_ROOT / name, bundle / name, ignore=shutil.ignore_patterns("__pycache__"))
        later_install = bundle / "scripts" / "install.py"

        for modified in (False, True):
            with self.subTest(modified=modified):
                project = self.tmp / f"retired-project-{modified}"
                home = self.tmp / f"retired-home-{modified}"
                project.mkdir()
                home.mkdir()
                initial = self.install(project=project, codex_home=home)
                self.assertEqual(initial.returncode, 0, initial.stdout + initial.stderr)
                retired = home / "skills" / SKILL_NAME / "ARCHITECTURE.md"
                before = retired.read_bytes()
                if modified:
                    before = b"USER edited retired document\n"
                    retired.write_bytes(before)
                command = [sys.executable, str(later_install), "--project", str(project), "--codex-home", str(home), "--force"]
                preserved = run(command, cwd=bundle)
                self.assertEqual(preserved.returncode, 0, preserved.stdout + preserved.stderr)
                self.assertEqual(retired.read_bytes(), before)
                pruned = run([*command, "--prune"], cwd=bundle)
                self.assertEqual(pruned.returncode, 0, pruned.stdout + pruned.stderr)
                if modified:
                    self.assertEqual(retired.read_bytes(), before)
                else:
                    self.assertFalse(retired.exists())
                    self.assertIn("removed   : 1", pruned.stdout)

    def test_reinstall_does_not_inherit_invalid_digest_for_omitted_agent(self) -> None:
        self.install()
        target = self.codex_home / "agents" / "luna-worker.toml"
        sentinel = target.read_bytes()
        manifest_path = self.write_manifest({str(target.resolve()): "g" * 64})
        result = self.install("--force", "--no-agent")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(target.read_bytes(), sentinel)
        self.assertNotIn(str(target.resolve()), json.loads(manifest_path.read_text(encoding="utf-8"))["files"])
        self.assertIn("invalid recorded SHA-256", result.stdout)

    def test_install_preserves_config_and_pins_each_role(self) -> None:
        config = self.codex_home / "config.toml"
        original = b"model = 'user-choice'\n[agents]\nenabled = false\n"
        config.write_bytes(original)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(config.read_bytes(), original)
        expected = {
            "luna-worker.toml": ("gpt-6-luna", "medium"),
            "luna-reviewer.toml": ("gpt-6-luna", "high"),
            "sol-senior.toml": ("gpt-6.1-sol", "high"),
            "sol-reviewer.toml": ("gpt-6.1-sol", "high"),
            "astra-consultant.toml": ("gpt-6-astra", "high"),
            "luna-state-editor.toml": ("gpt-6-luna", "low"),
        }
        for filename, (model, effort) in expected.items():
            text = (self.codex_home / "agents" / filename).read_text(encoding="utf-8")
            self.assertIn(f'model = "{model}"', text)
            self.assertIn(f'model_reasoning_effort = "{effort}"', text)

    def test_agent_conflict_aborts_all_writes(self) -> None:
        agent = self.codex_home / "agents" / "luna-worker.toml"
        agent.parent.mkdir(parents=True)
        user_content = 'name = "user_agent"\n'
        agent.write_text(user_content, encoding="utf-8")
        result = self.install()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(agent.read_text(encoding="utf-8"), user_content)
        self.assertFalse(self.skill_dir.exists())
        self.assertFalse((self.project / ".codex" / "orchestrator-install-manifest.json").exists())

    def test_uninstall_keeps_identical_agent_that_predated_install(self) -> None:
        source = REPO_ROOT / "templates" / "agents" / "luna-worker.toml"
        target = self.codex_home / "agents" / source.name
        target.parent.mkdir(parents=True)
        target.write_bytes(source.read_bytes())
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_bytes(), source.read_bytes())

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
                    import shlex
                    command_args = shlex.split(handler["command"], posix=True)
                    script = command_args[-1]
                    self.assertTrue(Path(script).is_file(), script)
                    # JSON keys are camelCase; snake_case is TOML-only.
                    self.assertNotIn("command_windows", handler)
                    if "commandWindows" in handler:
                        import base64
                        prefix = "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
                        self.assertTrue(handler["commandWindows"].startswith(prefix))
                        encoded = handler["commandWindows"][len(prefix):]
                        windows_source = base64.b64decode(encoded).decode("utf-16le")
                        self.assertIn(str(self.project), windows_source)
                        self.assertIn("exit $LASTEXITCODE", windows_source)

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
        if GIT_AVAILABLE:
            git(self.root, "init")

    def tearDown(self) -> None:
        cleanup_temporary_directory(self._tmp)

    def write_state(self, text: str, where: Optional[Path] = None) -> Path:
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

    def test_returns_unicode_state_without_writing_the_file(self) -> None:
        state = self.write_state("# Project State\n\n## Project intent\nship it — 東京\n")
        before = state.read_bytes()
        result = run_hook(
            INJECT_HOOK, {"hook_event_name": "SessionStart", "cwd": str(self.root)}, cwd=self.root
        )
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertIn("ship it — 東京", payload["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(state.read_bytes(), before, "SessionStart hook must never modify PROJECT_STATE.md")

    def test_snapshot_freshness_uses_only_a_helper_inside_git_root(self) -> None:
        helper = self.root / ".codex" / "hooks" / "orchestrate.py"
        helper.parent.mkdir(parents=True)
        shutil.copy2(REPO_ROOT / "scripts" / "orchestrate.py", helper)
        state = self.write_state(
            "# Project State\n<!-- orchestrator-snapshot:" + ("0" * 64) + " -->\n"
        )
        tracked = self.root / "src.txt"
        tracked.write_text("hello\n", encoding="utf-8")
        git(self.root, "config", "user.name", "Disposable Test")
        git(self.root, "config", "user.email", "disposable-test@example.invalid")
        self.assertEqual(git(self.root, "add", "-A").returncode, 0)
        self.assertEqual(git(self.root, "commit", "-m", "temporary test fixture").returncode, 0)
        tracked.write_text("changed after commit\n", encoding="utf-8")
        before = state.read_bytes()
        result = run_hook(
            INJECT_HOOK, {"hook_event_name": "SessionStart", "cwd": str(self.root)}, cwd=self.root
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("snapshot is stale", context)
        self.assertEqual(state.read_bytes(), before)

    def test_does_not_find_parent_state_outside_nearest_git_root(self) -> None:
        self.write_state("# Parent Project State\nparent secret sentinel\n")
        nested = self.root / "nested-repo"
        nested.mkdir()
        self.assertEqual(git(nested, "init").returncode, 0)
        result = run_hook(
            INJECT_HOOK, {"hook_event_name": "SessionStart", "cwd": str(nested)}, cwd=nested
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

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
        helper = self.root / ".codex" / "hooks" / "orchestrate.py"
        helper.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / "scripts" / "orchestrate.py", helper)
        self.tracked = self.root / "app.txt"
        self.tracked.write_text("v1\n", encoding="utf-8")
        git(self.root, "add", "-A")
        commit = git(self.root, "commit", "-m", "init")
        if commit.returncode != 0:
            self.skipTest(f"git commit unavailable: {commit.stderr}")

    def tearDown(self) -> None:
        cleanup_temporary_directory(self._tmp)

    def hook(self, payload: dict) -> subprocess.CompletedProcess:
        merged = {"SOL_DEEPSEEK_NUDGE_DIR": str(self.nudge_dir)}
        return run_hook(STOP_HOOK, payload, cwd=self.root, env=merged)

    def record_snapshot(self) -> None:
        result = run(
            [sys.executable, str(REPO_ROOT / "scripts" / "orchestrate.py"), "--project", str(self.root), "snapshot", "--json"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        fingerprint = json.loads(result.stdout)["state_fingerprint"]
        with self.state.open("a", encoding="utf-8") as stream:
            stream.write(f"\n<!-- orchestrator-snapshot:{fingerprint} -->\n")

    def test_silent_on_a_clean_tree(self) -> None:
        result = self.hook({"cwd": str(self.root), "turn_id": "t1"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_silent_when_state_is_newer_than_changes(self) -> None:
        self.tracked.write_text("v2\n", encoding="utf-8")
        self.record_snapshot()
        result = self.hook({"cwd": str(self.root), "turn_id": "t2"})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_nudges_once_when_state_is_stale(self) -> None:
        self.tracked.write_text("v3\n", encoding="utf-8")
        self.record_snapshot()
        self.tracked.write_text("changed after snapshot\n", encoding="utf-8")

        result = self.hook({"cwd": str(self.root), "turn_id": "turn-тест-東京"})
        self.assertEqual(result.returncode, 0)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("PROJECT_STATE.md", payload["reason"])

        again = self.hook({"cwd": str(self.root), "turn_id": "turn-тест-東京"})
        self.assertEqual(again.stdout.strip(), "")

    def test_respects_stop_hook_active(self) -> None:
        self.tracked.write_text("v4\n", encoding="utf-8")
        self.record_snapshot()
        self.tracked.write_text("changed after snapshot\n", encoding="utf-8")
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
        self.assertFalse((self.skill_dir / "SKILL.md").exists())
        self.assertFalse((self.codex_home / "agents" / "luna-worker.toml").exists())
        self.assertFalse((self.project / ".codex" / "hooks.json").exists())
        self.assertTrue(state.is_file())
        self.assertTrue((self.project / "AGENTS.md").is_file())

    def test_uninstall_keeps_modified_managed_files(self) -> None:
        self.install("--hooks")
        skill_file = self.skill_dir / "SKILL.md"
        skill_file.write_text("user edits\n", encoding="utf-8")
        agent = self.codex_home / "agents" / "luna-worker.toml"
        agent.write_text(agent.read_text(encoding="utf-8") + "# local change\n", encoding="utf-8")
        hooks_json = self.project / ".codex" / "hooks.json"
        hooks_json.write_text(hooks_json.read_text(encoding="utf-8") + " ", encoding="utf-8")

        result = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(skill_file.is_file())
        self.assertEqual(skill_file.read_text(encoding="utf-8"), "user edits\n")
        self.assertTrue(agent.is_file())
        self.assertTrue(hooks_json.is_file())
        self.assertTrue((self.project / ".codex" / "orchestrator-install-manifest.json").is_file())

    def test_manifest_retains_prior_hooks_and_agents_when_reinstall_options_are_omitted(self) -> None:
        self.install("--hooks")
        second = self.install("--force", "--no-agent")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        result = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.codex_home / "agents" / "luna-worker.toml").exists())
        self.assertFalse((self.project / ".codex" / "hooks.json").exists())

    def test_uninstall_dry_run_keeps_everything(self) -> None:
        self.install("--hooks")
        result = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home), "--dry-run"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.skill_dir / "SKILL.md").is_file())
        self.assertTrue((self.project / ".codex" / "hooks.json").is_file())

    def test_uninstall_ignores_forged_manifest_entry_for_config(self) -> None:
        config = self.codex_home / "config.toml"
        sentinel = "user configuration sentinel\n"
        config.write_text(sentinel, encoding="utf-8")
        manifest_path = self.project / ".codex" / "orchestrator-install-manifest.json"
        manifest_path.parent.mkdir(parents=True)
        files = {str(config.resolve()): hashlib.sha256(config.read_bytes()).hexdigest()}
        manifest = {"version": 1, "files": files}
        manifest["manifest_sha256"] = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(config.is_file())
        self.assertEqual(config.read_text(encoding="utf-8"), sentinel)

    def test_uninstall_ignores_unknown_skill_entry_and_its_empty_parent(self) -> None:
        self.install()
        custom = self.skill_dir / "user-custom.md"
        sentinel = b"USER sentinel\n"
        custom.write_bytes(sentinel)
        empty_parent = self.codex_home / "user-data" / "empty-folder"
        empty_parent.mkdir(parents=True)
        absent = empty_parent / "absent.txt"
        self.write_manifest({
            str(custom.resolve()): hashlib.sha256(sentinel).hexdigest(),
            str(absent.resolve()): hashlib.sha256(b"").hexdigest(),
        })
        result = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)],
            cwd=REPO_ROOT,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(custom.read_bytes(), sentinel)
        self.assertTrue(empty_parent.is_dir())
        self.assertIn("exact managed-file allowlist", result.stdout)

    @unittest.skipIf(os.name != "nt", "Windows directory junction behavior requires Windows")
    def test_project_codex_junction_blocks_install_and_state_purge(self) -> None:
        external = self.tmp / "external-codex"
        external.mkdir()
        state = external / "PROJECT_STATE.md"
        sentinel = "external state sentinel\n"
        state.write_text(sentinel, encoding="utf-8")
        link = self.project / ".codex"
        command = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(link), str(external)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if command.returncode != 0:
            self.skipTest(f"could not create a temporary directory junction: {command.stderr}")

        install = self.install("--hooks")
        self.assertEqual(install.returncode, 2, install.stdout + install.stderr)
        self.assertEqual(state.read_text(encoding="utf-8"), sentinel)
        uninstall = run(
            [sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home), "--purge-state"],
            cwd=REPO_ROOT,
        )
        self.assertEqual(uninstall.returncode, 2)
        self.assertEqual(state.read_text(encoding="utf-8"), sentinel)

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

    @unittest.skipIf(tomllib is None, 'independent fixture TOML check requires Python 3.11+')
    def test_verify_rejects_multiline_instructions_spoofing_real_toml_settings(self) -> None:
        self.install()
        agent = self.codex_home / 'agents' / 'sol-reviewer.toml'
        original = agent.read_bytes()
        prefix = ('name = "sol_reviewer"\nmodel = "gpt-6.1-sol"\n'
                  'model_reasoning_effort = "high"\nservice_tier = "standard"\n')
        fixtures = (
            ('agents.enabled', prefix + 'sandbox_mode = "read-only"\nagents.enabled = true\n'
             'developer_instructions = """\n[agents]\nenabled = false\n"""\n'),
            ('sandbox_mode', prefix + '"sandbox_mode" = "danger-full-access"\n'
             'developer_instructions = """\nsandbox_mode = "read-only"\n"""\n'
             '[agents]\nenabled = false\n'),
        )
        for setting, text in fixtures:
            with self.subTest(setting=setting):
                actual = tomllib.loads(text)
                if setting == 'agents.enabled':
                    self.assertIs(actual['agents']['enabled'], True)
                else:
                    self.assertEqual(actual['sandbox_mode'], 'danger-full-access')
                agent.write_text(text, encoding='utf-8')
                before = agent.read_bytes()
                result = self.verify('--json')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('agent sol_reviewer ' + setting, '\n'.join(json.loads(result.stdout)['errors']))
                self.assertEqual(agent.read_bytes(), before)
        agent.write_bytes(original)

    @unittest.skipIf(tomllib is None, 'independent fixture TOML check requires Python 3.11+')
    def test_verify_rejects_multiline_root_profile_spoof(self) -> None:
        self.install()
        profile = self.codex_home / 'orchestrator-director.config.toml'
        text = ('model = "gpt-6.1-sol"\nmodel_reasoning_effort = "high"\n'
                '"service_tier" = "fast"\ndeveloper_instructions = """\n'
                'service_tier = "standard"\n"""\n'
                '[agents]\nenabled = true\nmax_concurrent_threads_per_session = 4\n')
        self.assertEqual(tomllib.loads(text)['service_tier'], 'fast')
        profile.write_text(text, encoding='utf-8')
        before = profile.read_bytes()
        result = self.verify('--json')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('director profile service_tier', '\n'.join(json.loads(result.stdout)['errors']))
        self.assertEqual(profile.read_bytes(), before)

    def test_verify_passes_on_a_good_install(self) -> None:
        self.install("--hooks")
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("errors: 0", result.stdout)

    def test_verify_preserves_no_agent_install_semantics(self) -> None:
        self.install("--no-agent")
        # Ownership records do not store the install options. The verifier
        # needs an explicit absence policy instead of guessing from claims.
        default = self.verify('--json')
        self.assertEqual(default.returncode, 1, default.stdout + default.stderr)
        self.assertEqual(len([item for item in json.loads(default.stdout)['checks']
                              if item['name'].startswith('agent ') and item['name'].endswith(' present') and item['status'] == 'error']), 6)
        result = self.verify('--no-agent')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('explicit verifier --no-agent allows missing roles', result.stdout)
        self.assertIn('configuration was not verified', result.stdout)

    def test_verify_accepts_real_toml_syntax_and_ignores_multiline_examples(self) -> None:
        self.install()
        agent = self.codex_home / 'agents' / 'sol-reviewer.toml'
        original = agent.read_text(encoding='utf-8')
        for delimiter in ('"""', "'''"):
            with self.subTest(delimiter=delimiter):
                text = ("'name' = 'sol_reviewer'\n\"model\" = 'gpt-6.1-sol'\n"
                    'model_reasoning_effort = "high" # configured effort\n'
                    'service_tier = "standard"\nsandbox_mode = "read-only"\n'
                    f'developer_instructions = {delimiter}\n'
                    'sandbox_mode = "danger-full-access"\n[agents]\nenabled = true\n'
                    f'{delimiter}\n"agents"."enabled" = false\n')
                agent.write_text(text, encoding='utf-8')
                before = agent.read_bytes()
                result = self.verify('--json')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['errors'], [])
                self.assertEqual(agent.read_bytes(), before)
        agent.write_text(original, encoding='utf-8')

    def test_verify_rejects_invalid_toml_and_wrong_value_types(self) -> None:
        self.install()
        agent = self.codex_home / 'agents' / 'sol-reviewer.toml'
        original = agent.read_bytes()
        text = original.decode('utf-8').replace('\r\n', '\n')
        fixtures = (
            ('invalid syntax', text + '\ninvalid = [\n', 'TOML parses'),
            ('duplicate key', text.replace('enabled = false', 'enabled = false\nenabled = false'), 'TOML parses'),
            ('integer boolean', text.replace('enabled = false', 'enabled = 0'), 'agents.enabled'),
            ('wrong table type', text.replace('[agents]\nenabled = false', 'agents = "disabled"'), 'agents.enabled'),
        )
        for case, text, error in fixtures:
            with self.subTest(case=case):
                agent.write_text(text, encoding='utf-8')
                before = agent.read_bytes()
                result = self.verify('--json')
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn('agent sol_reviewer ' + error, '\n'.join(json.loads(result.stdout)['errors']))
                self.assertEqual(agent.read_bytes(), before)
        agent.write_bytes(original)
        agent.write_bytes(original + b'\n# invalid UTF-8: \xff\n')
        result = self.verify('--json')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('agent sol_reviewer TOML parses', '\n'.join(json.loads(result.stdout)['errors']))

    def test_no_agent_does_not_skip_existing_role_or_invalid_file_type(self) -> None:
        role_dir = self.codex_home / 'agents'
        role_dir.mkdir()
        agent = role_dir / 'sol-reviewer.toml'
        original = (REPO_ROOT / 'templates' / 'agents' / agent.name).read_bytes()
        agent.write_bytes(original)
        self.install('--no-agent')
        result = self.verify('--no-agent', '--json')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any(item['name'] == 'agent sol_reviewer sandbox_mode' for item in json.loads(result.stdout)['checks']))
        agent.write_bytes(original.replace(b'sandbox_mode = "read-only"', b'sandbox_mode = "danger-full-access"'))
        before = agent.read_bytes()
        result = self.verify('--no-agent', '--json')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('agent sol_reviewer sandbox_mode', '\n'.join(json.loads(result.stdout)['errors']))
        self.assertEqual(agent.read_bytes(), before)
        agent.unlink()
        agent.mkdir()
        result = self.verify('--no-agent', '--json')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('agent sol_reviewer TOML parses', '\n'.join(json.loads(result.stdout)['errors']))

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

    def test_verify_rejects_role_with_wrong_pinned_model_or_effort(self) -> None:
        self.install()
        agent = self.codex_home / "agents" / "astra-consultant.toml"
        text = agent.read_text(encoding="utf-8").replace(
            'model_reasoning_effort = "high"',
            'model_reasoning_effort = "medium"',
        )
        agent.write_text(text, encoding="utf-8")
        result = self.verify()
        self.assertEqual(result.returncode, 1)
        self.assertIn("agent astra_consultant model_reasoning_effort", result.stdout)

    def test_verify_rejects_drift_in_read_only_reviewer_settings_without_rewriting(self) -> None:
        self.install()
        role_files = (
            "luna-worker.toml", "luna-reviewer.toml", "luna-state-editor.toml",
            "sol-senior.toml", "sol-reviewer.toml", "astra-consultant.toml",
        )
        modified_files = {}
        for filename in role_files:
            role_file = self.codex_home / "agents" / filename
            original = role_file.read_text(encoding="utf-8")
            modified = original.replace('service_tier = "standard"', 'service_tier = "fast"')
            modified = modified.replace("enabled = false", "enabled = true")
            if filename == "sol-reviewer.toml":
                modified = modified.replace('sandbox_mode = "read-only"', 'sandbox_mode = "danger-full-access"')
            self.assertNotEqual(modified, original, f"fixture must alter {filename}")
            modified_files[role_file] = modified
            role_file.write_text(modified, encoding="utf-8")

        reinstall = self.install()
        self.assertEqual(reinstall.returncode, 3, reinstall.stdout + reinstall.stderr)
        for role_file, modified in modified_files.items():
            self.assertEqual(role_file.read_text(encoding="utf-8"), modified)

        result = self.verify("--json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        errors = "\n".join(json.loads(result.stdout)["errors"])
        for role in ("luna_worker", "luna_reviewer", "luna_state_editor", "sol_senior", "sol_reviewer", "astra_consultant"):
            self.assertIn(f"agent {role} service_tier", errors)
            self.assertIn(f"agent {role} agents.enabled", errors)
        self.assertIn("agent sol_reviewer sandbox_mode", errors)
        for role_file, modified in modified_files.items():
            self.assertEqual(role_file.read_text(encoding="utf-8"), modified)

    def test_verify_rejects_root_profile_drift_without_rewriting(self) -> None:
        self.install()
        profile = self.codex_home / "orchestrator-director.config.toml"
        original = profile.read_text(encoding="utf-8")
        modified = original.replace('service_tier = "standard"', 'service_tier = "fast"')
        modified = modified.replace("enabled = true", "enabled = false")
        self.assertNotEqual(modified, original, "fixture must alter the installed root profile contract")
        profile.write_text(modified, encoding="utf-8")

        result = self.verify("--json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        errors = "\n".join(json.loads(result.stdout)["errors"])
        self.assertIn("director profile service_tier", errors)
        self.assertIn("director profile agents.enabled", errors)
        self.assertEqual(profile.read_text(encoding="utf-8"), modified)

    def test_verify_warns_about_legacy_astra_deepseek_alias_without_editing_it(self) -> None:
        legacy = self.codex_home / "agents" / "astra-legacy.toml"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        original = 'name = "astra_flash_builder"\nmodel = "deepseek/model"\n'
        legacy.write_text(original, encoding="utf-8")
        self.install()
        result = self.verify()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("legacy Astra alias", result.stdout)
        self.assertEqual(legacy.read_text(encoding="utf-8"), original)

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
            with tempfile.TemporaryDirectory(prefix="sdo-e2e-hook-home-") as hook_home:
                hook_result = subprocess.run(
                    [sys.executable, str(installed_inject)], input=payload, capture_output=True,
                    text=True, encoding="utf-8", cwd=str(project), env=isolated_env(Path(hook_home)),
                    timeout=60, check=False,
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
