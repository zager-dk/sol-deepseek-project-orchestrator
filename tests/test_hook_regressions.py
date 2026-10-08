from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from test_support import cleanup_temporary_directory

REPO_ROOT = Path(__file__).resolve().parents[1]
STOP_HOOK = REPO_ROOT / "hooks" / "stop_project_state_check.py"


@unittest.skipUnless(shutil.which("git"), "git is required for Stop-hook regression tests")
class StopHookSnapshotFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sdo-hook-failure-")
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.git_config = Path(self.temp.name) / "gitconfig"
        self.git_config.write_text("", encoding="utf-8")
        self.nudge_dir = Path(self.temp.name) / "nudge-markers"
        self.state = self.root / ".codex" / "PROJECT_STATE.md"
        self.helper = self.root / ".codex" / "hooks" / "orchestrate.py"
        self.state.parent.mkdir(parents=True)
        self.helper.parent.mkdir(parents=True)
        self.state_text = (
            "# Project State\n"
            "<!-- orchestrator-snapshot:" + ("0" * 64) + " -->\n"
        )
        self.state.write_text(self.state_text, encoding="utf-8")
        self._write_helper_fails()
        self._git("init")
        self._git("config", "user.name", "Disposable Hook Test")
        self._git("config", "user.email", "hook-test@example.invalid")
        self._git("add", "-A")
        self._git("commit", "-m", "temporary fixture")

    def tearDown(self) -> None:
        cleanup_temporary_directory(self.temp)

    def _env(self) -> dict[str, str]:
        keep = ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "TEMP", "TMP")
        env = {key: os.environ[key] for key in keep if key in os.environ}
        home = str(Path(self.temp.name) / "home")
        env.update({
            "HOME": home,
            "USERPROFILE": home,
            "GIT_CONFIG_GLOBAL": str(self.git_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "SOL_DEEPSEEK_NUDGE_DIR": str(self.nudge_dir),
        })
        return env

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args], cwd=self.root, env=self._env(), capture_output=True,
            text=True, encoding="utf-8", timeout=30, check=False,
        )
        if result.returncode != 0:
            self.fail(f"git {' '.join(args)} failed: {result.stderr}")
        return result

    def _write_helper_fails(self) -> None:
        self.helper.write_text(
            "import sys\nsys.stderr.write('fixture snapshot denied\\n')\nsys.exit(2)\n",
            encoding="utf-8",
        )

    def _run_hook(self, *, turn_id: str, stop_hook_active: bool = False) -> subprocess.CompletedProcess[str]:
        payload = {
            "cwd": str(self.root),
            "turn_id": turn_id,
            "stop_hook_active": stop_hook_active,
        }
        return subprocess.run(
            [sys.executable, str(STOP_HOOK)], input=json.dumps(payload), cwd=self.root,
            env=self._env(), capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=False,
        )

    def test_helper_error_with_empty_status_emits_one_diagnostic_and_preserves_state(self) -> None:
        self.assertEqual(self._git("status", "--porcelain").stdout, "")
        before = self.state.read_bytes()

        first = self._run_hook(turn_id="snapshot-error-turn")
        self.assertEqual(first.returncode, 0, first.stderr)
        decision = json.loads(first.stdout)
        self.assertEqual(decision["decision"], "block")
        self.assertIn("could not be verified", decision["reason"])
        self.assertIn("exited with status 2", decision["reason"])
        self.assertEqual(self.state.read_bytes(), before)

        repeated = self._run_hook(turn_id="snapshot-error-turn")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(repeated.stdout.strip(), "")

        active = self._run_hook(turn_id="snapshot-error-active", stop_hook_active=True)
        self.assertEqual(active.returncode, 0, active.stderr)
        self.assertEqual(active.stdout.strip(), "")

    def test_valid_current_snapshot_with_empty_status_allows_stop(self) -> None:
        self.helper.write_text(
            "import json\n"
            "print(json.dumps({'fingerprint': 'f' * 64, 'state_fingerprint': '0' * 64, 'paths': []}))\n",
            encoding="utf-8",
        )
        self._git("add", "-A")
        self._git("commit", "-m", "valid helper fixture")
        self.assertEqual(self._git("status", "--porcelain").stdout, "")

        result = self._run_hook(turn_id="snapshot-current-turn")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")
        self.assertEqual(self.state.read_text(encoding="utf-8"), self.state_text)


if __name__ == "__main__":
    unittest.main()
