"""Regression coverage for installer ownership and hook safety.

All subprocess tests use throwaway HOME, CODEX_HOME, and Git configuration.
They never read or write the user's Codex configuration or credentials.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.util
import json
import io
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = ROOT / "scripts" / "install.py"
UNINSTALL_SCRIPT = ROOT / "scripts" / "uninstall.py"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_install.py"
SKILL_NAME = "sol-deepseek-project-orchestrator"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


INSTALLER = load_module("install", INSTALL_SCRIPT)
UNINSTALLER = load_module("installer_regression_uninstall", UNINSTALL_SCRIPT)


class IsolatedInstallerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="orchestrator-regression-")
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.codex_home = self.root / "codex-home"
        self.codex_home.mkdir()
        (self.codex_home / "config.toml").write_text("# isolated test home\n", encoding="utf-8")
        self.git_config = self.root / "gitconfig"
        self.git_config.write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def env(self, *, codex_home: Path | None = None) -> dict[str, str]:
        # Do not pass authentication, proxy, or user-specific configuration.
        keep = ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT", "COMSPEC", "TEMP", "TMP")
        result = {key: os.environ[key] for key in keep if key in os.environ}
        result.update({
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "CODEX_HOME": str(codex_home or self.codex_home),
            "GIT_CONFIG_GLOBAL": str(self.git_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        return result

    def project(self, name: str) -> Path:
        path = self.root / name
        path.mkdir()
        return path

    def install(self, project: Path, codex_home: Path | None = None, *extra: str):
        return subprocess.run(
            [sys.executable, str(INSTALL_SCRIPT), "--project", str(project), "--codex-home",
             str(codex_home or self.codex_home), *extra],
            cwd=ROOT, env=self.env(codex_home=codex_home), capture_output=True,
            text=True, encoding="utf-8", timeout=180, check=False,
        )

    def uninstall(self, project: Path, codex_home: Path | None = None):
        return subprocess.run(
            [sys.executable, str(UNINSTALL_SCRIPT), "--project", str(project), "--codex-home",
             str(codex_home or self.codex_home)],
            cwd=ROOT, env=self.env(codex_home=codex_home), capture_output=True,
            text=True, encoding="utf-8", timeout=180, check=False,
        )

    def verify(self, project: Path, *extra: str):
        return subprocess.run([sys.executable, str(VERIFY_SCRIPT), '--project', str(project),
            '--codex-home', str(self.codex_home), '--json', *extra], cwd=ROOT,
            env=self.env(), capture_output=True, text=True, encoding='utf-8', timeout=180)

    def preexisting_roles(self):
        agents = self.codex_home / 'agents'
        agents.mkdir(exist_ok=True)
        for filename in INSTALLER.AGENT_FILES:
            (agents / filename).write_bytes((ROOT / 'templates' / 'agents' / filename).read_bytes())
        return agents

    def test_verify_checks_all_six_preexisting_unowned_roles_and_rejects_tampering(self):
        project = self.project('verify-preexisting')
        agents = self.preexisting_roles()
        result = self.install(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest_path = project / '.codex' / INSTALLER.MANIFEST_NAME
        manifest_before = manifest_path.read_bytes()
        files = json.loads(manifest_before)['files']
        for filename in INSTALLER.AGENT_FILES:
            self.assertNotIn(str((agents / filename).resolve()), files)
        originals = {filename: (agents / filename).read_bytes() for filename in INSTALLER.AGENT_FILES}
        for filename in INSTALLER.AGENT_FILES:
            with self.subTest(filename=filename):
                agent = agents / filename
                agent.write_text(originals[filename].decode('utf-8').replace('enabled = false', 'enabled = true'), encoding='utf-8')
                before = agent.read_bytes()
                checked = self.verify(project)
                self.assertEqual(checked.returncode, 1, checked.stdout + checked.stderr)
                self.assertIn('agents.enabled', '\n'.join(json.loads(checked.stdout)['errors']))
                self.assertEqual(agent.read_bytes(), before)
                self.assertEqual(manifest_path.read_bytes(), manifest_before)
                agent.write_bytes(originals[filename])
        checked = self.verify(project)
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        payload = json.loads(checked.stdout)
        self.assertFalse(any('explicitly skipped' in message for message in payload['warnings']))
        self.assertEqual(len([item for item in payload['checks'] if item['name'].endswith('agents.enabled') and item['status'] == 'ok']), 7)

    def test_verify_no_agent_checks_reused_roles_and_does_not_infer_absence_from_manifest(self):
        project = self.project('verify-reused-optout')
        agents = self.preexisting_roles()
        result = self.install(project, self.codex_home, '--no-agent')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        manifest_path = project / '.codex' / INSTALLER.MANIFEST_NAME
        before_manifest = manifest_path.read_bytes()
        # There are no role claims, but all six configurations are present.
        good = self.verify(project, '--no-agent')
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        payload = json.loads(good.stdout)
        self.assertEqual(len([item for item in payload['checks'] if item['name'].startswith('agent ') and item['name'].endswith(' TOML parses')]), 6)
        for filename in INSTALLER.AGENT_FILES:
            with self.subTest(filename=filename):
                agent = agents / filename
                original = agent.read_bytes()
                agent.write_bytes(original.replace(b'enabled = false', b'enabled = true'))
                before = agent.read_bytes()
                bad = self.verify(project, '--no-agent')
                self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
                self.assertEqual(agent.read_bytes(), before)
                agent.write_bytes(original)
        # Deleting every unclaimed reused role must not masquerade as --no-agent.
        for filename in INSTALLER.AGENT_FILES:
            (agents / filename).unlink()
        missing = self.verify(project)
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertEqual(len([error for error in json.loads(missing.stdout)['errors'] if ' present:' in error]), 6)
        allowed = self.verify(project, '--no-agent')
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertEqual(manifest_path.read_bytes(), before_manifest)

    def test_verify_hook_operand_supports_data_dir_and_rejects_missing_or_unsupported_script(self):
        project = self.project('verify-hook-data-dir')
        installed = self.install(project, self.codex_home, '--hooks', '--data-dir', 'ledger data')
        self.assertEqual(installed.returncode, 0, installed.stdout + installed.stderr)
        hooks_path = project / '.codex' / 'hooks.json'
        payload = json.loads(hooks_path.read_text(encoding='utf-8'))
        handlers = [handler for groups in payload['hooks'].values() for group in groups
                    for handler in group.get('hooks', [])]
        self.assertEqual(len(handlers), 2)
        good = self.verify(project)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

        # Quoted executable and script operands may both contain spaces.
        for event, script_name in (('SessionStart', 'inject_project_state.py'),
                                   ('Stop', 'stop_project_state_check.py')):
            handlers_by_event = next(group['hooks'] for group in payload['hooks'][event])
            handlers_by_event[0]['command'] = shlex.join([
                'C:/python runtime/python.exe',
                str(project / '.codex' / 'hooks' / script_name),
            ])
        hooks_path.write_text(json.dumps(payload), encoding='utf-8')
        quoted = self.verify(project)
        self.assertEqual(quoted.returncode, 0, quoted.stdout + quoted.stderr)

        data_file = project / 'ledger data'
        data_file.write_text('not a script', encoding='utf-8')
        handlers[0]['command'] = shlex.join([
            'C:/python runtime/python.exe', str(project / '.codex' / 'hooks' / 'missing.py'),
            '--data-dir', str(data_file),
        ])
        handlers[1]['command'] = shlex.join([
            'C:/python runtime/python.exe', str(project / '.codex' / 'hooks' / 'stop_project_state_check.py'),
        ])
        hooks_path.write_text(json.dumps(payload), encoding='utf-8')
        missing = self.verify(project)
        self.assertEqual(missing.returncode, 1, missing.stdout + missing.stderr)
        self.assertTrue(any('hook script exists' in error for error in json.loads(missing.stdout)['errors']))

        handlers[0]['command'] = shlex.join([
            'C:/python runtime/python.exe', str(project / '.codex' / 'hooks' / 'inject_project_state.py'),
            '--data-dir', str(data_file), 'unexpected-extra',
        ])
        hooks_path.write_text(json.dumps(payload), encoding='utf-8')
        unsupported = self.verify(project)
        self.assertEqual(unsupported.returncode, 1, unsupported.stdout + unsupported.stderr)
        self.assertTrue(any('hook script exists' in error for error in json.loads(unsupported.stdout)['errors']))

        handlers[0]['command'] = "'C:/python runtime/python.exe' 'unterminated"
        hooks_path.write_text(json.dumps(payload), encoding='utf-8')
        malformed = self.verify(project)
        self.assertEqual(malformed.returncode, 1, malformed.stdout + malformed.stderr)
        self.assertTrue(any('invalid quoted command' in error for error in json.loads(malformed.stdout)['errors']))

    def test_verify_fails_closed_when_parser_unavailable_or_role_unreadable(self):
        project = self.project('verify-parser-failure')
        result = self.install(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        verifier = load_module('verifier_fault_regression', VERIFY_SCRIPT)
        args = ['--project', str(project), '--codex-home', str(self.codex_home), '--json']
        roles = {self.codex_home / 'agents' / filename: (self.codex_home / 'agents' / filename).read_bytes()
                 for filename in INSTALLER.AGENT_FILES}
        with mock.patch.object(verifier, 'tomllib', None), contextlib.redirect_stdout(io.StringIO()) as output:
            code = verifier.main(args)
        self.assertEqual(code, 1)
        self.assertIn('TOML parser unavailable', '\n'.join(json.loads(output.getvalue())['errors']))
        original_read = Path.read_text
        def denied(path, *args, **kwargs):
            if path in roles: raise PermissionError('fixture config read denied')
            return original_read(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', denied), contextlib.redirect_stdout(io.StringIO()) as output:
            code = verifier.main(args + ['--no-agent'])
        self.assertEqual(code, 1)
        self.assertEqual(len([error for error in json.loads(output.getvalue())['errors'] if 'fixture config read denied' in error]), 6)
        for path, content in roles.items():
            self.assertEqual(path.read_bytes(), content)

    def test_shared_codex_home_survives_uninstall_in_both_orders_and_reinstall(self) -> None:
        for first, second in (("A", "B"), ("B", "A")):
            with self.subTest(first_removed=first):
                shared = self.root / f"shared-{first}"
                shared.mkdir()
                a, b = self.project(f"project-a-{first}"), self.project(f"project-b-{first}")
                for project in (a, b):
                    result = self.install(project, shared)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                skill = shared / "skills" / SKILL_NAME / "SKILL.md"
                role = shared / "agents" / "luna-worker.toml"
                self.assertTrue(skill.is_file())
                self.assertTrue(role.is_file())
                removed_first = a if first == "A" else b
                remaining = b if first == "A" else a
                registry_path = shared / INSTALLER.REGISTRY_NAME
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                self.assertEqual(len(registry["files"][str(skill.resolve())]["owners"]), 2)
                result = self.uninstall(removed_first, shared)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(skill.is_file(), "removing one project must preserve shared installation for the other")
                registry = json.loads(registry_path.read_text(encoding="utf-8"))
                self.assertEqual(len(registry["files"][str(skill.resolve())]["owners"]), 1)
                self.assertTrue(role.is_file())
                again = self.install(removed_first, shared)
                self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
                result = self.uninstall(remaining, shared)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(skill.is_file(), "the reinstalled project's manifest still depends on shared files")

    def test_shared_preexisting_user_files_are_preserved_across_project_uninstall(self) -> None:
        a, b = self.project("user-shared-a"), self.project("user-shared-b")
        agent = self.codex_home / "agents" / "luna-worker.toml"
        agent.parent.mkdir(parents=True)
        sentinel = (ROOT / "templates" / "agents" / "luna-worker.toml").read_bytes()
        agent.write_bytes(sentinel)
        for project in (a, b):
            result = self.install(project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for project in (a, b):
            result = self.uninstall(project)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(agent.read_bytes(), sentinel)

    def test_create_plan_does_not_overwrite_user_files_created_before_apply(self) -> None:
        project = self.project("create-race")
        codex_home = self.root / "race-home"
        codex_home.mkdir()
        state = project / ".codex" / "PROJECT_STATE.md"
        agents = project / "AGENTS.md"
        plan = INSTALLER.build_plan(
            project, codex_home, with_hooks=False, with_agents_md=True,
            with_agent=True, prune=False, plan=INSTALLER.Plan(),
        )
        self.assertIn(INSTALLER.CREATE, [item.action for item in plan.items if item.path in (state, agents)])
        state.parent.mkdir(parents=True)
        state.write_text("user state added after planning\n", encoding="utf-8")
        agents.write_text("user instructions added after planning\n", encoding="utf-8")
        applied = INSTALLER.apply_plan(plan, force=False, dry_run=False,
                                       roots=(project.resolve(), codex_home.resolve()))
        self.assertIn(str(state), applied["preserved"])
        self.assertIn(str(agents), applied["preserved"])
        self.assertEqual(state.read_text(encoding="utf-8"), "user state added after planning\n")
        self.assertEqual(agents.read_text(encoding="utf-8"), "user instructions added after planning\n")

    def test_identical_preexisting_home_file_is_not_added_as_shared_claim(self) -> None:
        project = self.project("identical-preexisting")
        target = self.codex_home / "agents" / "luna-worker.toml"
        target.parent.mkdir(parents=True)
        target.write_bytes((ROOT / "templates" / "agents" / target.name).read_bytes())
        result = self.install(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        registry = json.loads((self.codex_home / INSTALLER.REGISTRY_NAME).read_text(encoding="utf-8"))
        self.assertNotIn(str(target.resolve()), registry["files"])
        removed = self.uninstall(project)
        self.assertEqual(removed.returncode, 0, removed.stdout + removed.stderr)
        self.assertTrue(target.is_file())

    def test_lock_rejects_competing_operation_and_releases_after_crash(self) -> None:
        project = self.project("locked-project")
        with INSTALLER.installation_lock(self.codex_home):
            blocked = self.install(project)
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertIn("another install/uninstall is active", blocked.stderr)
        crash_script = (
            "import os, sys; from pathlib import Path; "
            f"sys.path.insert(0, {str(ROOT / 'scripts')!r}); "
            "from install import installation_lock; "
            f"lock = installation_lock(Path({str(self.codex_home)!r})); "
            "lock.__enter__(); os._exit(17)"
        )
        crashed = subprocess.run([sys.executable, "-c", crash_script], cwd=ROOT, env=self.env(),
                                 capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
        self.assertEqual(crashed.returncode, 17)
        recovered = self.install(project)
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertTrue((self.codex_home / INSTALLER.LOCK_NAME).is_file())

    def test_uninstall_retains_failed_entries_in_manifest_for_retry(self) -> None:
        project = self.project("failed-uninstall")
        result = self.install(project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        target = self.codex_home / "agents" / "luna-worker.toml"
        manifest_path = project / ".codex" / "orchestrator-install-manifest.json"
        original_unlink = Path.unlink

        def deny_target(path: Path, *args, **kwargs):
            if path == target:
                raise PermissionError("deterministic test denial")
            return original_unlink(path, *args, **kwargs)

        with mock.patch.object(Path, "unlink", deny_target):
            code = UNINSTALLER.main(["--project", str(project), "--codex-home", str(self.codex_home)])
        self.assertNotEqual(code, 0)
        self.assertTrue(target.is_file())
        self.assertTrue(manifest_path.is_file())
        remaining = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
        self.assertIn(str(target.resolve()), remaining)
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), remaining[str(target.resolve())])

    def test_posix_hook_command_preserves_shell_metacharacters_in_interpreter_and_script(self) -> None:
        interpreter = str(self.root / "bin space %PATH% & [snow 雪]" / "interpreter $HOME ' ` ;.exe")
        script = str(self.root / "project space" / "hook $HOME %TEMP% & ' ` ;()[snow 雪].py")
        with mock.patch.object(INSTALLER, "posix_interpreter", return_value=str(interpreter)):
            command = INSTALLER.hook_command(Path(script), use_windows=False)
        self.assertIsNotNone(command)
        expected = f"{shlex.quote(interpreter)} {shlex.quote(script)}"
        self.assertEqual(command, expected)
        if os.name == "posix":
            bindir = self.root / "bin space 'quote" / "dollar$backtick`semi;()é"
            bindir.mkdir(parents=True)
            executable = bindir / "interpreter $HOME ' ` ;.sh"
            actual_script = bindir / "hook $HOME ' ` ;().py"
            received = bindir / "received.txt"
            executable.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\" > \"$RECEIVED\"\n", encoding="utf-8")
            executable.chmod(0o755)
            actual_script.write_text("# marker\n", encoding="utf-8")
            env = self.env()
            env["RECEIVED"] = str(received)
            with mock.patch.object(INSTALLER, "posix_interpreter", return_value=str(executable)):
                executable_command = INSTALLER.hook_command(actual_script, use_windows=False)
            run = subprocess.run(executable_command, shell=True, cwd=self.root, env=env,
                                 capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(received.read_text(encoding="utf-8").splitlines(), [str(actual_script)])

    def test_windows_hook_command_encodes_paths_as_data_not_shell_text(self) -> None:
        interpreter = r'C:\temporary home\python "quoted" $HOME %PATH% & (x) 雪.exe'
        script = self.root / 'hook space "quote" $HOME %TEMP% & (x); 雪.py'
        with mock.patch.object(INSTALLER, "windows_interpreter", return_value=interpreter):
            command = INSTALLER.hook_command(script, use_windows=True)
        prefix = "powershell.exe -NoLogo -NoProfile -NonInteractive -EncodedCommand "
        self.assertTrue(command.startswith(prefix))
        encoded = command[len(prefix):]
        decoded = base64.b64decode(encoded).decode("utf-16le")
        self.assertIn(interpreter.replace("'", "''"), decoded)
        self.assertIn(str(script).replace("'", "''"), decoded)
        self.assertEqual(command.split()[-1], encoded)
        self.assertNotIn(interpreter, command)
        self.assertNotIn(str(script), command)
