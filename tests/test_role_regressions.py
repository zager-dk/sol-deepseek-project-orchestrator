"""Structural and executable-contract checks for configured role routing."""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - actionable skip on Python < 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
ROLES = ROOT / "templates" / "agents"
EXPECTED_CHILDREN = {
    "luna-worker.toml": ("luna_worker", "gpt-6-luna", "medium"),
    "luna-reviewer.toml": ("luna_reviewer", "gpt-6-luna", "high"),
    "luna-state-editor.toml": ("luna_state_editor", "gpt-6-luna", "low"),
    "sol-senior.toml": ("sol_senior", "gpt-6.1-sol", "high"),
    "sol-reviewer.toml": ("sol_reviewer", "gpt-6.1-sol", "high"),
    "astra-consultant.toml": ("astra_consultant", "gpt-6-astra", "high"),
}


class RoleConfigurationRegressions(unittest.TestCase):
    @unittest.skipIf(tomllib is None, "TOML structure requires Python 3.11+")
    def test_exact_child_role_set_and_supported_configuration_structure(self):
        self.assertEqual({p.name for p in ROLES.glob("*.toml")}, set(EXPECTED_CHILDREN))
        for filename, (name, model, effort) in EXPECTED_CHILDREN.items():
            with self.subTest(role=filename):
                data = tomllib.loads((ROLES / filename).read_text(encoding="utf-8"))
                self.assertEqual(data["name"], name)
                self.assertEqual(data["model"], model)
                self.assertEqual(data["model_reasoning_effort"], effort)
                self.assertIsInstance(data["service_tier"], str)
                self.assertIs(data["agents"]["enabled"], False)
                self.assertIn("developer_instructions", data)
        reviewer = tomllib.loads((ROLES / "sol-reviewer.toml").read_text(encoding="utf-8"))
        self.assertEqual(reviewer["sandbox_mode"], "read-only")

    @unittest.skipIf(tomllib is None, "TOML structure requires Python 3.11+")
    def test_director_is_a_primary_config_profile_not_a_child(self):
        self.assertFalse((ROLES / "orchestrator-director.toml").exists())
        profile = tomllib.loads((ROOT / "templates" / "orchestrator-director.config.toml").read_text(encoding="utf-8"))
        example = tomllib.loads((ROOT / "templates" / "codex.config.example.toml").read_text(encoding="utf-8"))
        self.assertEqual(example["model"], profile["model"])
        self.assertEqual(example["service_tier"], profile["service_tier"])
        self.assertEqual(example["model_reasoning_effort"], profile["model_reasoning_effort"])
        self.assertEqual(profile["model"], "gpt-6.1-sol")
        self.assertEqual(profile["model_reasoning_effort"], "high")
        self.assertIsInstance(profile["service_tier"], str)
        self.assertIs(profile["agents"]["enabled"], True)
        self.assertGreater(profile["agents"]["max_concurrent_threads_per_session"], 0)

    def test_runtime_cli_exposes_documented_manual_workflow(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "orchestrate.py"), "--help"],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for command in ("init", "add", "plan-review", "assign", "start", "submit", "review", "integrate", "complete", "recover", "replan", "escalate"):
            with self.subTest(command=command):
                self.assertIn(command, result.stdout)


if __name__ == "__main__":
    unittest.main()
