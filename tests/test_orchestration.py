"""Behavioral tests for the project-local orchestration ledger."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
import stat
from unittest import mock
from pathlib import Path
from test_support import cleanup_temporary_directory

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'orchestrate.py'

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project'; self.root.mkdir()
        self.home = self.base / 'home'; self.home.mkdir()
        self.codex_home = self.base / 'codex-home'; self.codex_home.mkdir()
        self.hooks = self.base / 'empty-hooks'; self.hooks.mkdir()
        self.git_config = self.base / 'gitconfig'
        self.git_config.write_text(
            '[user]\n\tname = Test\n\temail = test@example.invalid\n'
            '[core]\n\thooksPath = ' + str(self.hooks).replace('\\', '/') +
            '\n\tfilemode = true\n[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n',
            encoding='utf-8',
        )
        self.env = os.environ.copy()
        self.env.update({'HOME': str(self.home), 'USERPROFILE': str(self.home),
                         'CODEX_HOME': str(self.codex_home), 'GIT_CONFIG_GLOBAL': str(self.git_config),
                         'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'})
        self.git('init', '-q')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('config', 'user.name', 'Test')
        (self.root / 'base.txt').write_text('base\n')
        self.git('add', 'base.txt'); self.git('commit', '-qm', 'base')
        self.call('init')

    def tearDown(self): cleanup_temporary_directory(self.tmp)

    def git(self, *args, input=None):
        return subprocess.run(['git', *args], cwd=self.root, env=self.env, check=True, text=True,
                              encoding='utf-8', capture_output=True, input=input)

    def call(self, *args, ok=True):
        if args and args[0] == 'review':
            args = (*args, '--fresh-context-attested', '--context-item', 'contract',
                    '--context-item', 'diff', '--context-item', 'relevant-code',
                    '--context-item', 'verification-results')
        result = subprocess.run([sys.executable, str(SCRIPT), '--project', str(self.root), *args],
                                cwd=self.root, env=self.env, text=True, encoding='utf-8', capture_output=True)
        if ok and result.returncode: self.fail(result.stderr)
        if not ok and result.returncode == 0: self.fail(f'expected failure: {args}')
        return result

    def add(self, tid, scope='a.py', depends='', risk='low'):
        result = self.call('add', tid, '--goal', tid, '--depends-on', depends, '--scope', scope,
                           '--risk', risk, '--acceptance', 'observable behavior', '--actor', 'director')
        self.call('plan-review', tid, '--actor', 'director', '--director', 'director',
                  '--reviewer', 'acceptance-planner', '--contract-version', '1',
                  '--scenario', 'observable behavior holds', '--fresh-context-attested',
                  '--context-item', 'contract', '--context-item', 'diff',
                  '--context-item', 'relevant-code', '--context-item', 'verification-results')
        return result

    def db(self): return json.loads((self.root/'.codex'/'ORCHESTRATOR.json').read_text())

    def test_dependencies_duplicate_assignment_and_resource_collisions(self):
        self.add('A', 'Src\\Widget.py')
        self.add('B', 'src/widget.PY')
        self.add('C', 'other.py', 'A')
        self.call('assign', 'C', '--owner', 'luna-1', '--actor', 'director', ok=False)
        self.call('assign', 'A', '--owner', 'luna-1', '--actor', 'director')
        self.call('assign', 'A', '--owner', 'luna-2', '--actor', 'director', ok=False)
        self.add('D', 'src/widget.py')
        self.call('assign', 'D', '--owner', 'luna-2', '--actor', 'director', ok=False)
        self.add('E', 'src')
        self.call('assign', 'E', '--owner', 'luna-2', '--actor', 'director', ok=False)
        self.add('WHOLE', '.')
        self.call('assign', 'WHOLE', '--owner', 'luna-2', '--actor', 'director', ok=False)
        self.call('start', 'A', '--actor', 'luna-1')
        self.call('interrupt', 'A', '--actor', 'someone-else', ok=False)

    def test_integrated_owner_remains_reserved_until_completion(self):
        self.add('A', 'first.py')
        self.call('assign', 'A', '--owner', 'worker', '--actor', 'director')
        self.call('start', 'A', '--actor', 'worker')
        self.call('submit', 'A', '--actor', 'worker')
        self.call('review', 'A', '--reviewer', 'reviewer', '--result', 'pass',
                  '--check', 'PASS; command=focused; result=exit 0; evidence=verified',
                  '--findings', 'accepted')
        self.call('integrate', 'A', '--actor', 'director',
                  '--check', 'PASS; command=combined; result=exit 0; evidence=verified')
        self.assertEqual(self.db()['tasks']['A']['state'], 'integrated')

        self.add('B', 'different.py')
        ledger = self.root / '.codex' / 'ORCHESTRATOR.json'
        before = ledger.read_bytes()
        rejected = self.call('assign', 'B', '--owner', 'worker', '--actor', 'director', ok=False)
        self.assertIn('already has an active task', rejected.stderr)
        self.assertEqual(ledger.read_bytes(), before)

        self.call('complete', 'A', '--actor', 'director',
                  '--check', 'PASS; command=completion; result=exit 0; evidence=verified')
        self.call('assign', 'B', '--owner', 'worker', '--actor', 'director')

    def test_interruption_requires_director_recovery_and_preserves_context(self):
        self.add('A'); self.call('assign','A','--owner','luna-old','--actor','director')
        self.call('start','A','--actor','luna-old'); self.call('interrupt','A','--actor','luna-old')
        self.call('recover','A','--owner','luna-new','--actor','director','--context','patch and logs retained',ok=False)
        self.call('recover','A','--owner','luna-new','--actor','director','--context','patch and logs retained','--old-agent-interrupted')
        t=self.db()['tasks']['A']
        self.assertEqual(t['owner'],'luna-new'); self.assertEqual(t['previous_owner'],'luna-old')
        self.assertEqual(t['recovery_context'],'patch and logs retained')
        self.call('start','A','--actor','luna-new'); self.call('submit','A','--actor','luna-new')
        self.call('review','A','--reviewer','luna-old','--result','fail','--findings','same prior author',ok=False)

    def test_review_requires_distinct_author_and_records_unrun_and_outcomes(self):
        self.add('A'); self.call('assign','A','--owner','author','--actor','director'); self.call('start','A','--actor','author')
        (self.root/'a.py').write_text('change')
        self.call('submit','A','--actor','author')
        self.call('review','A','--reviewer','author','--result','pass','--findings','ok','--check','PASS; command=unit tests; result=exit 0; evidence=test run 0',ok=False)
        self.call('review','A','--reviewer','independent-luna','--result','pass','--check','python -m unittest: exit 0; output at test run 1','--unrun','manual UI test','--findings','ok',ok=False)
        self.call('review','A','--reviewer','independent-luna','--result','pass','--check','PASS; command=python -m unittest; result=exit 0; evidence=test run 1','--unrun','manual UI test','--findings','ok')
        self.assertEqual(self.db()['tasks']['A']['evidence'][-1]['unrun'],['manual UI test'])
        self.call('integrate','A','--actor','director','--check','PASS; command=combined tree unit tests; result=exit 0; evidence=test run 2')
        self.call('complete','A','--actor','director','--check','PASS; command=combined tree unit tests; result=exit 0; evidence=test run 3')

    def test_failed_correction_bundle_requires_bounded_director_escalation(self):
        self.add('A'); self.call('assign','A','--owner','luna','--actor','director'); self.call('start','A','--actor','luna')
        (self.root/'a.py').write_text('first attempt'); self.call('submit','A','--actor','luna')
        self.call('review','A','--reviewer','reviewer','--result','fail','--findings','repro: case fails')
        (self.root/'a.py').write_text('one correction bundle')
        self.call('submit','A','--actor','luna')
        self.call('review','A','--reviewer','reviewer','--result','fail','--findings','correction failed')
        self.call('submit','A','--actor','luna')
        self.call('review','A','--reviewer','reviewer','--result','fail','--findings','extra round forbidden',ok=False)
        self.call('escalate','A','--actor','director','--director','director','--owner','sol-senior-1','--owner-role','sol_senior','--reason','complexity after one correction bundle','--context','repro=case; prior attempts=initial, one correction','--old-agent-interrupted')
        t=self.db()['tasks']['A']
        self.assertEqual(t['owner'],'sol-senior-1'); self.assertEqual(t['escalations'],1)
        self.assertIn('prior attempts',t['escalation_history'][0]['context'])
        self.assertEqual(t['state'],'assigned')
        prior_attempt=t['attempt']
        self.call('start','A','--actor','sol-senior-1')
        t=self.db()['tasks']['A']
        self.assertEqual(t['state'],'in_progress')
        self.assertEqual(t['attempt'],prior_attempt+1)
        self.assertLess(t['evidence'][-1]['attempt'],t['attempt'])
        self.call('escalate','A','--actor','director','--director','director','--owner','sol-2','--owner-role','sol_senior','--reason','again','--context','again','--old-agent-interrupted',ok=False)

    def test_posix_git_path_split_preserves_literal_backslash(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('orchestrate_path_test',SCRIPT)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        name=r'..\outside.txt'
        self.assertEqual(module.git_path_parts(name, platform='posix'), [name])
        with self.assertRaisesRegex(module.OrchestrationError,'unsafe Git path'):
            module.git_path_parts('../outside.txt', platform='posix')

    def test_escalation_requires_stop_declaration_and_independent_owner(self):
        self.add('ESC')
        self.call('assign','ESC','--owner','worker','--actor','director')
        self.call('start','ESC','--actor','worker')
        for finding in ('first correction failed','second correction failed'):
            self.call('submit','ESC','--actor','worker')
            self.call('review','ESC','--reviewer','reviewer','--result','fail','--findings',finding)
        self.assertEqual(self.db()['tasks']['ESC']['state'],'in_progress')
        common=('ESC','--actor','director','--director','director','--owner-role','sol_senior',
                '--reason','bounded correction allowance exhausted','--context','repro=case; attempts=two')

        before=(self.root/'.codex'/'ORCHESTRATOR.json').read_bytes()
        missing_stop=self.call('escalate',*common,'--owner','sol-senior-stop-missing',ok=False)
        self.assertIn('not authentication or proof',missing_stop.stderr)
        self.assertEqual((self.root/'.codex'/'ORCHESTRATOR.json').read_bytes(),before)
        self.assertEqual(self.db()['tasks']['ESC']['owner'],'worker')

        planner=self.call('escalate',*common,'--owner','acceptance-planner','--old-agent-interrupted',ok=False)
        self.assertIn('acceptance planner cannot become',planner.stderr)
        self.assertEqual((self.root/'.codex'/'ORCHESTRATOR.json').read_bytes(),before)
        self.assertEqual(self.db()['tasks']['ESC']['owner'],'worker')

        self.call('escalate',*common,'--owner','sol-senior-independent','--old-agent-interrupted')
        task=self.db()['tasks']['ESC']
        self.assertEqual(task['owner'],'sol-senior-independent')
        self.assertEqual(task['state'],'assigned')
        self.assertEqual(task['owner_history'][-1],'sol-senior-independent')
        self.assertTrue(task['escalation_history'][-1]['previous_owner_stopped_manual_attestation'])
        previous_attempt=task['attempt']
        self.call('start','ESC','--actor','sol-senior-independent')
        task=self.db()['tasks']['ESC']
        self.assertEqual(task['state'],'in_progress')
        self.assertEqual(task['attempt'],previous_attempt+1)

    def test_exact_snapshot_and_high_risk_independent_gate(self):
        self.add('H', 'security.py', risk='high'); self.call('assign','H','--owner','author','--actor','director')
        self.call('start','H','--actor','author'); (self.root/'security.py').write_text('secure')
        self.call('submit','H','--actor','author')
        self.call('review','H','--reviewer','luna-reviewer','--result','pass','--check','PASS; command=security tests; result=exit 0; evidence=run 1','--findings','verified','--senior-verified','--senior-reviewer','sol-instance-1',ok=False)
        self.call('review','H','--reviewer','luna-reviewer','--result','pass','--check','PASS; command=security tests; result=exit 0; evidence=run 1','--findings','verified','--senior-verified','--senior-reviewer','sol-instance-1','--senior-role','sol_reviewer')
        self.call('integrate','H','--actor','director','--check','PASS; command=combined security tests; result=exit 0; evidence=run 2','--senior-verified','--senior-reviewer','sol-instance-1','--senior-role','sol_reviewer')
        (self.root/'security.py').write_text('changed after review')
        self.call('complete','H','--actor','director','--check','PASS; command=verify; result=exit 0; evidence=run 3',ok=False)

    def test_astra_gate_requires_canonical_role_and_director_resolution(self):
        self.add('H','security.py',risk='high'); self.call('assign','H','--owner','author','--actor','director')
        self.call('start','H','--actor','author'); (self.root/'security.py').write_text('secure'); self.call('submit','H','--actor','author')
        self.call('consult','H','--actor','director','--director','director','--consultant','astra-instance','--consultant-role','astra_consultant','--question','architecture?','--budget','one response','--outcome','use invariant X')
        self.call('review','H','--reviewer','luna-reviewer','--result','pass','--check','PASS; command=security checks; result=exit 0; evidence=run 1','--findings','passed','--astra-consulted','--director-resolved',ok=False)
        self.call('review','H','--reviewer','luna-reviewer','--result','pass','--check','PASS; command=security checks; result=exit 0; evidence=run 1','--findings','passed','--astra-consulted','--director-resolved','--director-decision','Adopt invariant X')
        self.call('integrate','H','--actor','director','--check','PASS; command=combined checks; result=exit 0; evidence=run 2','--astra-consulted','--director-resolved','--director-decision','Adopt invariant X')
        ev=self.db()['tasks']['H']['integration_evidence']['astra_resolution']
        self.assertEqual(ev['consultant_role'],'astra_consultant')
        self.assertEqual(ev['model'],'gpt-6-astra')
        self.assertEqual(ev['director_decision'],'Adopt invariant X')
        self.assertEqual(ev['consultant_identity'],'astra-instance')
        self.assertEqual(ev['identity_is_manual_attestation'],'true')
        task=self.db()['tasks']['H']
        self.assertEqual(task['evidence'][-1]['reviewer'],'luna-reviewer')
        self.assertEqual(task['evidence'][-1]['astra_resolution']['consultant_identity'],'astra-instance')

    def test_astra_and_luna_cannot_reuse_one_instance_at_review_or_integration(self):
        self.add('H','security.py',risk='high')
        self.call('assign','H','--owner','author','--actor','director')
        self.call('start','H','--actor','author')
        (self.root/'security.py').write_text('secure')
        self.call('submit','H','--actor','author')
        self.call('consult','H','--actor','director','--director','director',
                  '--consultant','shared-instance','--consultant-role','astra_consultant',
                  '--question','architecture?','--budget','one response','--outcome','use invariant X')
        astra=['--astra-consulted','--director-resolved','--director-decision','Adopt invariant X']
        review=['review','H','--result','pass','--check',
                'PASS; command=security checks; result=exit 0; evidence=run 1','--findings','passed']
        rejected=self.call(*review,'--reviewer','shared-instance',*astra,ok=False)
        self.assertIn('separate instance from the Luna reviewer',rejected.stderr)
        self.assertEqual(self.db()['tasks']['H']['evidence'],[])

        # A separate Sol permits Luna's review, but integration must not replace
        # that stronger check with an Astra consultation by the recorded Luna.
        senior=['--senior-verified','--senior-reviewer','independent-sol','--senior-role','sol_reviewer']
        self.call(*review,'--reviewer','shared-instance',*senior)
        integration=['integrate','H','--actor','director','--check',
                     'PASS; command=combined checks; result=exit 0; evidence=run 2']
        rejected=self.call(*integration,*astra,ok=False)
        self.assertIn('separate instance from the Luna reviewer',rejected.stderr)
        self.assertEqual(self.db()['tasks']['H']['state'],'ready_for_review')
        self.assertNotIn('integration_evidence',self.db()['tasks']['H'])
        self.call(*integration,*senior)
        evidence=self.db()['tasks']['H']['integration_evidence']['senior_verifier']
        self.assertEqual(evidence['identity'],'independent-sol')
        self.assertEqual(evidence['model'],'gpt-6.1-sol')

    def test_sol_and_luna_cannot_reuse_one_instance_at_review_or_integration(self):
        self.add('H','security.py',risk='high')
        self.call('assign','H','--owner','author','--actor','director')
        self.call('start','H','--actor','author'); self.call('submit','H','--actor','author')
        review=['review','H','--reviewer','luna-reviewer','--result','pass','--check',
                'PASS; command=security checks; result=exit 0; evidence=run 1','--findings','passed']
        shared=['--senior-verified','--senior-reviewer','luna-reviewer','--senior-role','sol_reviewer']
        rejected=self.call(*review,*shared,ok=False)
        self.assertIn('separate instance from the Luna reviewer',rejected.stderr)
        self.assertEqual(self.db()['tasks']['H']['evidence'],[])
        distinct=['--senior-verified','--senior-reviewer','independent-sol','--senior-role','sol_reviewer']
        self.call(*review,*distinct)
        task=self.db()['tasks']['H']
        self.assertEqual(task['evidence'][-1]['reviewer'],'luna-reviewer')
        self.assertEqual(task['evidence'][-1]['senior_verifier']['identity'],'independent-sol')
        integration=['integrate','H','--actor','director','--check',
                     'PASS; command=combined checks; result=exit 0; evidence=run 2']
        rejected=self.call(*integration,*shared,ok=False)
        self.assertIn('separate instance from the Luna reviewer',rejected.stderr)
        self.assertEqual(self.db()['tasks']['H']['state'],'ready_for_review')
        self.call(*integration,*distinct)
        self.assertEqual(self.db()['tasks']['H']['integration_evidence']['senior_verifier']['identity'],'independent-sol')

    def test_canonical_privileged_role_models_match_templates(self):
        source=Path(__file__).resolve().parents[1]/'templates'/'agents'
        self.assertIn('model = "gpt-6.1-sol"',(source/'sol-senior.toml').read_text())
        self.assertIn('model = "gpt-6-astra"',(source/'astra-consultant.toml').read_text())

    def test_snapshot_includes_untracked_deletions_renames_and_excludes_state(self):
        (self.root/'new.txt').write_text('new')
        (self.root/'base.txt').unlink()
        self.git('add','-A'); self.git('commit','-qm','rename')
        self.git('mv','new.txt','renamed.txt')
        snap=json.loads(self.call('snapshot','--json').stdout)
        self.assertIn('renamed.txt',snap['paths'])
        (self.root/'.codex'/'PROJECT_STATE.md').write_text('updated')
        same=json.loads(self.call('snapshot','--json').stdout)
        self.assertEqual(snap['fingerprint'],same['fingerprint'])
        (self.root/'untracked').write_text('x')
        self.assertIn('untracked',json.loads(self.call('snapshot','--json').stdout)['paths'])

    def test_snapshot_decodes_unicode_git_paths_and_renames(self):
        old=Path('данные')/'проба.txt'; new=Path('данные')/'готово.txt'
        (self.root/old).parent.mkdir(); (self.root/old).write_text('unicode content')
        self.git('add',str(old)); self.git('commit','-qm','unicode path')
        self.git('mv',str(old),str(new))
        snap=json.loads(self.call('snapshot','--json').stdout)
        self.assertIn(old.as_posix(),snap['paths']); self.assertIn(new.as_posix(),snap['paths'])

    def test_stop_hook_notices_head_drift_when_worktree_is_clean(self):
        (self.root/'.gitignore').write_text('.codex/\n')
        self.git('add','.gitignore'); self.git('commit','-qm','ignore local state')
        state=self.root/'.codex'/'PROJECT_STATE.md'; state.parent.mkdir(exist_ok=True); state.write_text('state\n')
        import shutil
        helper_dir=state.parent/'hooks'; helper_dir.mkdir(exist_ok=True)
        shutil.copyfile(SCRIPT,helper_dir/'orchestrate.py')
        fingerprint=json.loads(self.call('snapshot','--json').stdout)['state_fingerprint']
        state.write_text(f'state\n<!-- orchestrator-snapshot:{fingerprint} -->\n')
        (self.root/'base.txt').write_text('committed change\n')
        self.git('add','base.txt'); self.git('commit','-qm','head-only project change')
        with tempfile.TemporaryDirectory() as nudge_dir:
            env=self.env.copy(); env['SOL_DEEPSEEK_NUDGE_DIR']=nudge_dir
            run=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[1]/'hooks'/'stop_project_state_check.py')],cwd=self.root,input=json.dumps({'cwd':str(self.root),'turn_id':str(self.root)}),text=True,encoding='utf-8',capture_output=True,env=env)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('HEAD changed with no dirty paths',json.loads(run.stdout)['reason'])

    def test_snapshot_changes_when_only_index_blob_changes(self):
        app=self.root/'app.txt'; app.write_text('stage A'); self.git('add','app.txt')
        app.write_text('working'); before=json.loads(self.call('snapshot','--json').stdout)
        app.write_text('stage B'); self.git('add','app.txt'); app.write_text('working')
        after=json.loads(self.call('snapshot','--json').stdout)
        self.assertEqual(before['paths'],after['paths'])
        self.assertNotEqual(before['index_digest'],after['index_digest'])
        self.assertNotEqual(before['fingerprint'],after['fingerprint'])
        before=json.loads(self.call('snapshot','--json').stdout)
        os.utime(app,None)
        self.call('snapshot','--json')
        after=json.loads(self.call('snapshot','--json').stdout)
        self.assertEqual(before['fingerprint'],after['fingerprint'])

    def test_staged_bookkeeping_does_not_stale_snapshot(self):
        state=self.root/'.codex'/'PROJECT_STATE.md'; state.write_text('state A'); self.git('add','.codex/PROJECT_STATE.md')
        before=json.loads(self.call('snapshot','--json').stdout)
        state.write_text('state B'); self.git('add','.codex/PROJECT_STATE.md')
        after=json.loads(self.call('snapshot','--json').stdout)
        self.assertEqual(before['fingerprint'],after['fingerprint'])

    def test_state_fingerprint_ignores_state_only_commit_but_exact_review_fingerprint_does_not(self):
        state=self.root/'.codex'/'PROJECT_STATE.md'; state.write_text('state A')
        self.git('add','.codex/PROJECT_STATE.md'); self.git('commit','-qm','state A')
        before=json.loads(self.call('snapshot','--json').stdout)
        state.write_text('state B'); self.git('add','.codex/PROJECT_STATE.md'); self.git('commit','-qm','state B')
        after=json.loads(self.call('snapshot','--json').stdout)
        self.assertEqual(before['state_fingerprint'],after['state_fingerprint'])
        self.assertNotEqual(before['fingerprint'],after['fingerprint'])

    def runtime_module(self):
        spec = importlib.util.spec_from_file_location('snapshot_regression_runtime', SCRIPT)
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        return runtime

    def test_snapshot_cannot_read_clean_tracked_or_untracked_content(self):
        runtime = self.runtime_module()
        new = self.root / 'new.txt'
        new.write_text('untracked data')
        original = Path.read_bytes
        with mock.patch.dict(os.environ, self.env):
            for target in (self.root / 'base.txt', new):
                with self.subTest(target=target.name):
                    def denied(path):
                        if path == target: raise PermissionError('fixture read denied')
                        return original(path)
                    with mock.patch.object(Path, 'read_bytes', denied):
                        with self.assertRaisesRegex(runtime.OrchestrationError, 'cannot verify worktree path'):
                            runtime.snapshot(self.root)

    def test_snapshot_fails_closed_on_lstat_or_readlink_error(self):
        runtime = self.runtime_module()
        target = self.root / 'base.txt'
        original = Path.lstat
        def denied(path, *args, **kwargs):
            if path == target: raise PermissionError('fixture stat denied')
            return original(path, *args, **kwargs)
        with mock.patch.dict(os.environ, self.env):
            with mock.patch.object(Path, 'lstat', denied):
                with self.assertRaisesRegex(runtime.OrchestrationError, 'cannot verify worktree path'):
                    runtime.snapshot(self.root)
            # Fault injection avoids needing Windows symlink privileges.
            def link_stat(path, *args, **kwargs):
                info = original(path, *args, **kwargs)
                if path == target:
                    values = list(info)
                    values[0] = stat.S_IFLNK | 0o777
                    return os.stat_result(values)
                return info
            with mock.patch.object(Path, 'lstat', link_stat), mock.patch.object(runtime.os, 'readlink', side_effect=PermissionError('fixture readlink denied')):
                with self.assertRaisesRegex(runtime.OrchestrationError, 'cannot verify worktree path'):
                    runtime.snapshot(self.root)

    def test_snapshot_fails_closed_when_file_changes_during_read(self):
        runtime = self.runtime_module()
        target = self.root / 'base.txt'
        original = Path.read_bytes
        def changing(path):
            result = original(path)
            if path == target: path.write_bytes(result + b'concurrent edit')
            return result
        with mock.patch.dict(os.environ, self.env), mock.patch.object(Path, 'read_bytes', changing):
            with self.assertRaisesRegex(runtime.OrchestrationError, 'changed during snapshot'):
                runtime.snapshot(self.root)

    def test_snapshot_fails_closed_on_successful_git_inventory_warning(self):
        runtime = self.runtime_module()
        original = runtime.subprocess.run
        def warning(args, **kwargs):
            result = original(args, **kwargs)
            if 'status' in args:
                result.stderr = b'warning: could not open directory unreadable/: Permission denied\n'
            return result
        with mock.patch.dict(os.environ, self.env), mock.patch.object(runtime.subprocess, 'run', warning):
            with self.assertRaisesRegex(runtime.OrchestrationError, 'could not be verified'):
                runtime.snapshot(self.root)

    def test_git_preserves_raw_path_line_endings(self):
        runtime = self.runtime_module()
        output = b'?? literal\r\nfilename\0'
        result = subprocess.CompletedProcess(['git'], 0, output, b'')
        with mock.patch.object(runtime.subprocess, 'run', return_value=result):
            self.assertEqual(runtime.git(self.root, 'status', '-z'), output.decode('utf-8'))

    def test_snapshot_rechecks_earlier_hidden_path_after_reading_other_files(self):
        runtime = self.runtime_module()
        target = self.root / 'base.txt'
        self.git('update-index', '--assume-unchanged', 'base.txt')
        later = self.root / 'later.txt'
        later.write_text('later content')
        original = Path.read_bytes
        def changing(path):
            result = original(path)
            if path == later: target.write_text('hidden concurrent content')
            return result
        with mock.patch.dict(os.environ, self.env), mock.patch.object(Path, 'read_bytes', changing):
            with self.assertRaisesRegex(runtime.OrchestrationError, 'changed during snapshot'):
                runtime.snapshot(self.root)

    def test_snapshot_binds_index_conflict_stages_and_modes(self):
        self.git('config', 'core.filemode', 'true')
        first = self.git('hash-object', '-w', '--stdin', input='stage one').stdout.strip()
        second = self.git('hash-object', '-w', '--stdin', input='stage two').stdout.strip()
        def conflict(mode, stage):
            # NUL termination prevents Windows stdin newline conversion from
            # appending CR to Git's raw path and silently ignoring the entry.
            result = self.git('update-index', '-z', '--index-info', input=(
                '0 ' + '0' * len(first) + '\tbase.txt\0' +
                f'100644 {first} 1\tbase.txt\0{mode} {second} {stage}\tbase.txt\0'))
            self.assertEqual(result.stderr, '')
            self.assertIn(f'{mode} {second} {stage}\tbase.txt', self.git('ls-files', '--stage').stdout)
        conflict('100644', 2)
        before = json.loads(self.call('snapshot', '--json').stdout)
        conflict('100755', 2)
        mode_changed = json.loads(self.call('snapshot', '--json').stdout)
        conflict('100755', 3)
        stage_changed = json.loads(self.call('snapshot', '--json').stdout)
        self.assertNotEqual(before['index_digest'], mode_changed['index_digest'])
        self.assertNotEqual(mode_changed['index_digest'], stage_changed['index_digest'])
        self.assertNotEqual(mode_changed['fingerprint'], stage_changed['fingerprint'])

    def test_snapshot_keeps_index_and_flags_unchanged_on_stat_cache_drift(self):
        target = self.root / 'base.txt'
        before = json.loads(self.call('snapshot', '--json').stdout)
        os.utime(target, None)
        index = self.root / '.git' / 'index'
        index_bytes = index.read_bytes()
        flags = self.git('ls-files', '-v', '-z').stdout
        after = json.loads(self.call('snapshot', '--json').stdout)
        self.assertEqual(before['fingerprint'], after['fingerprint'])
        self.assertEqual(index.read_bytes(), index_bytes)
        self.assertEqual(self.git('ls-files', '-v', '-z').stdout, flags)

    def test_snapshot_hashes_ignored_worktree_leftover_after_staged_deletion(self):
        self.git('rm', '--cached', 'base.txt')
        (self.root / '.gitignore').write_text('base.txt\n')
        self.git('add', '.gitignore')
        before = json.loads(self.call('snapshot', '--json').stdout)
        (self.root / 'base.txt').write_text('ignored but formerly tracked contents')
        after = json.loads(self.call('snapshot', '--json').stdout)
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])

    def test_snapshot_supports_materialized_git_symlink_as_regular_file(self):
        self.git('config', 'core.symlinks', 'false')
        blob = self.git('hash-object', '-w', '--stdin', input='first-target').stdout.strip()
        self.git('update-index', '--add', '--cacheinfo', f'120000,{blob},alias')
        (self.root / 'alias').write_text('first-target')
        before = json.loads(self.call('snapshot', '--json').stdout)
        (self.root / 'alias').write_text('second-target')
        after = json.loads(self.call('snapshot', '--json').stdout)
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])

    def test_snapshot_rejects_absent_skip_worktree_and_sparse_checkout_paths(self):
        self.git('update-index', '--skip-worktree', 'base.txt')
        (self.root / 'base.txt').unlink()
        rejected = self.call('snapshot', '--json', ok=False)
        self.assertIn('absent skip-worktree/sparse path', rejected.stderr)
        (self.root / 'base.txt').write_text('base\n')
        self.git('update-index', '--no-skip-worktree', 'base.txt')
        for directory in ('included', 'omitted'):
            (self.root / directory).mkdir()
            (self.root / directory / 'data.txt').write_text(directory)
        self.git('add', 'included', 'omitted')
        self.git('commit', '-qm', 'sparse fixture')
        self.git('sparse-checkout', 'init', '--cone', '--sparse-index')
        self.git('sparse-checkout', 'set', 'included')
        self.assertFalse((self.root / 'omitted' / 'data.txt').exists())
        rejected = self.call('snapshot', '--json', ok=False)
        self.assertIn('absent skip-worktree/sparse path', rejected.stderr)

    def test_snapshot_rejects_directory_replacing_tracked_file(self):
        (self.root / 'base.txt').unlink()
        (self.root / 'base.txt').mkdir()
        rejected = self.call('snapshot', '--json', ok=False)
        self.assertIn('unsupported worktree file type', rejected.stderr)

    @unittest.skipUnless(os.name == 'posix', 'POSIX symlink type/content regression')
    def test_snapshot_hashes_link_target_without_following_it(self):
        target = self.root.parent / 'external'
        target.write_text('external one')
        link = self.root / 'base.txt'
        link.unlink()
        link.symlink_to(target)
        before = json.loads(self.call('snapshot', '--json').stdout)
        target.write_text('external two')
        same = json.loads(self.call('snapshot', '--json').stdout)
        self.assertEqual(before['fingerprint'], same['fingerprint'])
        link.unlink()
        link.symlink_to(self.root.parent / 'other-external')
        after = json.loads(self.call('snapshot', '--json').stdout)
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])

    def test_lock_fails_closed_and_scope_rejects_traversal(self):
        ledger=self.root/'.codex'/'ORCHESTRATOR.json'
        before=ledger.read_bytes()
        lock=self.root/'.codex'/'ORCHESTRATOR.lock'; lock.write_text('unknown owner')
        self.call('add','X','--goal','x','--scope','x','--acceptance','y','--actor','director',ok=False)
        self.assertEqual(ledger.read_bytes(),before)
        lock.unlink()
        self.call('add','X','--goal','x','--scope','../outside','--acceptance','y','--actor','director',ok=False)

    def test_failed_atomic_replace_preserves_ledger_and_history(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location('orchestrate_under_test',SCRIPT)
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        module.selected_dir(self.root,None)
        before=(self.root/'.codex'/'ORCHESTRATOR.json').read_bytes()
        db=module.load(self.root); module.log(db,None,'synthetic', 'test')
        original=module.os.replace
        try:
            def fail_replace(*_args): raise OSError('synthetic replace failure')
            module.os.replace=fail_replace
            with self.assertRaisesRegex(OSError,'synthetic replace failure'):
                module.save(self.root,db)
        finally:
            module.os.replace=original
        self.assertEqual((self.root/'.codex'/'ORCHESTRATOR.json').read_bytes(),before)
        self.assertFalse(list((self.root/'.codex').glob('ORCHESTRATOR.*.tmp')))

    def test_symlink_scope_alias_is_resolved(self):
        target=self.root/'real.py'; target.write_text('x')
        alias=self.root/'alias.py'
        try: alias.symlink_to(target)
        except (OSError, NotImplementedError): self.skipTest('symlink creation unavailable')
        self.add('A','real.py'); self.add('B','alias.py')
        self.call('assign','A','--owner','luna-a','--actor','director')
        self.call('assign','B','--owner','luna-b','--actor','director',ok=False)

    def test_codex_junction_storage_is_rejected_without_following_it(self):
        outside=Path(self.tmp.name).parent / (self.root.name+'-outside')
        outside.mkdir(exist_ok=True)
        codex=self.root/'.codex'
        try:
            import shutil
            shutil.rmtree(codex)
            if os.name=='nt':
                command=f"New-Item -ItemType Junction -Path '{codex}' -Target '{outside}' | Out-Null"
                result=subprocess.run(['powershell','-NoProfile','-Command',command],text=True,capture_output=True)
                if result.returncode: self.skipTest('junction creation unavailable: '+result.stderr.strip())
            else:
                codex.symlink_to(outside,target_is_directory=True)
            self.call('init',ok=False)
            self.assertFalse((outside/'ORCHESTRATOR.json').exists())
        finally:
            try:
                if os.name=='nt' and (codex.exists() or codex.is_symlink()): os.rmdir(codex)
                elif codex.is_symlink(): codex.unlink()
            except OSError: pass
            try: outside.rmdir()
            except OSError: pass

if __name__ == '__main__': unittest.main()
