"""Offline adaptive install and real Git isolation/integration regression tests."""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_install import TempRepoCase, REPO_ROOT, VERIFY, UNINSTALL, GIT_AVAILABLE, git, run

HELPER = REPO_ROOT / "skill" / "scripts" / "prepare_worktrees.py"
spec = importlib.util.spec_from_file_location("prepare_worktrees", HELPER)
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


class AdaptiveInstallTests(TempRepoCase):
    def test_legacy_defaults_keep_single_worker(self):
        self.assertEqual(self.install().returncode, 0)
        self.assertFalse((self.codex_home / "agents/deepseek-integrator.toml").exists())
        result = run([sys.executable, str(VERIFY), "--project", str(self.project), "--codex-home", str(self.codex_home)], cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_adaptive_install_verify_repeat_uninstall(self):
        self.assertEqual(self.install("--adaptive", "--hooks").returncode, 0)
        integrator = self.codex_home / "agents/deepseek-integrator.toml"
        self.assertTrue(integrator.is_file())
        helper = self.skill_dir / "scripts/prepare_worktrees.py"
        self.assertEqual(helper.read_bytes(), HELPER.read_bytes())
        result = run([sys.executable, str(VERIFY), "--project", str(self.project), "--codex-home", str(self.codex_home), "--adaptive", "--self-test"], cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        again = self.install("--adaptive", "--hooks")
        self.assertEqual(again.returncode, 0)
        self.assertIn("created   : 0", again.stdout)
        self.assertIn("updated   : 0", again.stdout)
        result = run([sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)], cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0)
        self.assertFalse(integrator.exists())
        self.assertTrue((self.project / ".codex/PROJECT_STATE.md").is_file())

    def test_integrator_conflict_blocks_all_writes_then_force_preserves_backup(self):
        agent = self.codex_home / "agents/deepseek-integrator.toml"
        agent.parent.mkdir()
        agent.write_text("local custom integrator\n", encoding="utf-8")
        result = self.install("--adaptive")
        self.assertEqual(result.returncode, 3)
        self.assertFalse(self.skill_dir.exists())
        self.assertEqual(self.install("--adaptive", "--force").returncode, 0)
        self.assertEqual(agent.with_name(agent.name + ".bak").read_text(), "local custom integrator\n")

    def test_no_agent_remains_authoritative_with_adaptive_flag(self):
        self.assertEqual(self.install("--adaptive", "--no-agent").returncode, 0)
        self.assertFalse((self.codex_home / "agents").exists())

    def test_uninstall_keeps_customized_agent_definitions(self):
        self.install("--adaptive")
        for name in ("deepseek-worker.toml", "deepseek-integrator.toml"):
            (self.codex_home / "agents" / name).write_text("# custom\n", encoding="utf-8")
        result = run([sys.executable, str(UNINSTALL), "--project", str(self.project), "--codex-home", str(self.codex_home)], cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0)
        for name in ("deepseek-worker.toml", "deepseek-integrator.toml"):
            self.assertEqual((self.codex_home / "agents" / name).read_text(), "# custom\n")

    @unittest.skipIf(sys.version_info < (3, 11), "stdlib TOML parser requires 3.11")
    def test_agent_and_example_toml_parse_with_explicit_routes(self):
        import tomllib
        for filename, name in (("deepseek-worker.toml", "deepseek_worker"), ("deepseek-integrator.toml", "deepseek_integrator")):
            data = tomllib.loads((REPO_ROOT / "templates/agents" / filename).read_text(encoding="utf-8"))
            self.assertEqual(data["name"], name)
            self.assertEqual(data["model"], "deepseek/deepseek-v4.1-flash")
            self.assertEqual(data["model_reasoning_effort"], "high")
        config = tomllib.loads((REPO_ROOT / "templates/codex.config.example.toml").read_text(encoding="utf-8"))
        self.assertEqual(config["agents"]["max_concurrent_threads_per_session"], 3)

    def test_adaptive_verify_fails_when_integrator_is_missing(self):
        self.install()
        result = run([sys.executable, str(VERIFY), "--project", str(self.project), "--codex-home", str(self.codex_home), "--adaptive"], cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 1)
        self.assertIn("integrator present", result.stdout)

    def test_upgrade_preserves_state_agents_and_legacy_alias(self):
        self.install("--agents-md")
        state = self.project / ".codex/PROJECT_STATE.md"
        state.write_text("# Accepted milestone\n", encoding="utf-8")
        policy = (self.project / "AGENTS.md").read_bytes()
        alias = self.codex_home / "agents/astra-flash-builder.toml"
        alias.write_text('name = "astra_flash_builder"\n', encoding="utf-8")
        (self.skill_dir / "SKILL.md").write_text("legacy skill\n", encoding="utf-8")
        self.assertEqual(self.install("--adaptive").returncode, 3)
        self.assertEqual(self.install("--adaptive", "--force", "--agents-md").returncode, 0)
        self.assertEqual(state.read_text(), "# Accepted milestone\n")
        self.assertEqual((self.project / "AGENTS.md").read_bytes(), policy)
        self.assertEqual(alias.read_text(), 'name = "astra_flash_builder"\n')


@unittest.skipUnless(GIT_AVAILABLE, "Git required")
class WorktreeTests(TempRepoCase):
    def setUp(self):
        super().setUp()
        state = self.project / ".codex/PROJECT_STATE.md"
        state.parent.mkdir()
        state.write_text("# Baseline state\n", encoding="utf-8")
        (self.project / "seed.txt").write_text("seed\n", encoding="utf-8")
        git(self.project, "add", ".codex/PROJECT_STATE.md", "seed.txt")
        result = git(self.project, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "baseline")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.workspaces = self.tmp / "isolated"

    def plan(self, count=2, task="fixture"):
        return workspace.plan_worktrees(self.project, self.workspaces, task, count)

    def test_one_two_three_workspaces_share_baseline(self):
        for count in (1, 2, 3):
            with self.subTest(count=count):
                plan = workspace.prepare(self.plan(count, f"task-{count}"))
                self.assertEqual(len(plan["workspaces"]), count + (count > 1))
                for entry in plan["workspaces"]:
                    path = Path(entry["path"])
                    self.assertEqual(git(path, "rev-parse", "HEAD").stdout.strip(), plan["baseline"])
                    self.assertEqual(git(path, "status", "--porcelain").stdout.strip(), "")
                self.assertEqual(json.loads(Path(plan["manifest"]).read_text())["workers"], count)

    def test_two_stream_integration_preserves_main_state_and_binary_additions(self):
        plan = workspace.prepare(self.plan())
        a, b, integration = [Path(x["path"]) for x in plan["workspaces"]]
        (a / "adapter-a.bin").write_bytes(bytes(range(256)))
        (b / "adapter-b.txt").write_text("B\n", encoding="utf-8")
        (b / "seed.txt").unlink()
        self.assertFalse((self.project / "adapter-a.bin").exists())
        self.assertFalse((b / "adapter-a.bin").exists())
        shas = []
        for path, files in ((a, ["adapter-a.bin"]), (b, ["adapter-b.txt", "seed.txt"])):
            self.assertEqual(git(path, "add", "--", *files).returncode, 0)
            result = git(path, "-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "explicit local fixture commit")
            self.assertEqual(result.returncode, 0, result.stderr)
            shas.append(git(path, "rev-parse", "HEAD").stdout.strip())
        result = git(integration, "cherry-pick", "--no-commit", *shas)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((integration / "adapter-a.bin").read_bytes(), bytes(range(256)))
        self.assertTrue((integration / "adapter-b.txt").is_file())
        self.assertFalse((integration / "seed.txt").exists())
        self.assertTrue((self.project / "seed.txt").is_file())
        self.assertEqual((integration / ".codex/PROJECT_STATE.md").read_bytes(), (self.project / ".codex/PROJECT_STATE.md").read_bytes())
        self.assertEqual(git(self.project, "status", "--porcelain").stdout.strip(), "")

    def test_dirty_tree_is_rejected_without_side_effects(self):
        (self.project / "untracked.txt").write_text("keep me")
        with self.assertRaisesRegex(workspace.WorkspaceError, "clean"):
            self.plan()
        self.assertFalse(self.workspaces.exists())

    def test_paths_ids_counts_and_subdirectory_are_rejected(self):
        for task in ("../escape", "Task", "foo/bar", "-bad"):
            with self.assertRaises(workspace.WorkspaceError):
                self.plan(task=task)
        for count in (0, 4):
            with self.assertRaises(workspace.WorkspaceError):
                self.plan(count)
        with self.assertRaises(workspace.WorkspaceError):
            workspace.plan_worktrees(self.project, self.project, "nested", 2)
        with self.assertRaisesRegex(workspace.WorkspaceError, "repository root"):
            workspace.plan_worktrees(self.project / ".codex", self.workspaces, "nested", 2)

    def test_project_changed_after_preflight_is_rejected(self):
        plan = self.plan()
        (self.project / "seed.txt").write_text("changed after planning\n")
        with self.assertRaisesRegex(workspace.WorkspaceError, "changed since preflight"):
            workspace.prepare(plan)
        self.assertFalse(self.workspaces.exists())

    def test_existing_branch_or_task_is_rejected_before_any_creation(self):
        self.assertEqual(git(self.project, "branch", "sdo/fixture/worker-2").returncode, 0)
        with self.assertRaisesRegex(workspace.WorkspaceError, "branch already exists"):
            self.plan()
        self.assertFalse(self.workspaces.exists())
        task = self.workspaces / "occupied"
        task.mkdir(parents=True)
        with self.assertRaisesRegex(workspace.WorkspaceError, "already exists"):
            self.plan(task="occupied")

    def test_partial_failure_retains_manifest_and_existing_workspace(self):
        plan = self.plan()
        real_git = workspace.git
        def fail_second(project, *args):
            if "sdo/fixture/worker-2" in args:
                raise workspace.WorkspaceError("fixture failure")
            return real_git(project, *args)
        with patch.object(workspace, "git", side_effect=fail_second):
            with self.assertRaisesRegex(workspace.WorkspaceError, "partial setup preserved"):
                workspace.prepare(plan)
        saved = json.loads(Path(plan["manifest"]).read_text())
        self.assertTrue(saved["workspaces"][0]["created"])
        self.assertFalse(saved["workspaces"][1]["created"])
        self.assertTrue(Path(saved["workspaces"][0]["path"]).is_dir())

    def test_cli_dry_run_does_not_write(self):
        result = run([sys.executable, str(HELPER), "--project", str(self.project), "--workspace-root", str(self.workspaces), "--task", "preview", "--workers", "3", "--dry-run"], cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["workers"], 3)
        self.assertFalse(self.workspaces.exists())


if __name__ == "__main__":
    unittest.main()
