"""Regression coverage for review freshness, reassignment, and exact snapshots.

Each case uses a disposable Git repository and isolated user/Git configuration.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import importlib.util
import shutil
from unittest import mock
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'orchestrate.py'


class IsolatedRuntimeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'project'
        self.root.mkdir()
        self.home = Path(self.tmp.name) / 'home'
        self.codex_home = Path(self.tmp.name) / 'codex-home'
        self.home.mkdir()
        self.codex_home.mkdir()
        self.git_config = Path(self.tmp.name) / 'gitconfig'
        self.hooks = Path(self.tmp.name) / 'empty-hooks'
        self.hooks.mkdir()
        self.git_config.write_text(
            '[user]\n\tname = Regression Test\n\temail = test@example.invalid\n'
            '[core]\n\thooksPath = ' + str(self.hooks).replace('\\', '/') +
            '\n\tfilemode = true\n[commit]\n\tgpgsign = false\n[tag]\n\tgpgsign = false\n',
            encoding='utf-8',
        )
        self.env = os.environ.copy()
        self.env.update({
            'HOME': str(self.home),
            'USERPROFILE': str(self.home),
            'CODEX_HOME': str(self.codex_home),
            'GIT_CONFIG_GLOBAL': str(self.git_config),
            'GIT_CONFIG_NOSYSTEM': '1',
            'GIT_TERMINAL_PROMPT': '0',
        })
        self.git('init', '-q')
        (self.root / 'tracked.txt').write_text('base\n', encoding='utf-8')
        self.git('add', 'tracked.txt')
        self.git('commit', '-qm', 'base')
        self.call('init')

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args, cwd=None, check=True, input=None):
        return subprocess.run(
            ['git', *args], cwd=cwd or self.root, env=self.env,
            check=check, text=True, encoding='utf-8', input=input, capture_output=True,
        )

    def call(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), '--project', str(self.root), *args],
            cwd=self.root, env=self.env, text=True, capture_output=True,
        )
        if ok and result.returncode:
            self.fail(result.stderr)
        if not ok and result.returncode == 0:
            self.fail(f'expected failure: {args}')
        return result

    def add(self, tid='T-1', *, scope='tracked.txt', risk='low'):
        self.call('add', tid, '--goal', 'regression task', '--depends-on', '',
                  '--priority', '50', '--risk', risk, '--scope', scope,
                  '--acceptance', 'observable result', '--actor', 'director')

    def db(self):
        return json.loads((self.root / '.codex' / 'ORCHESTRATOR.json').read_text(encoding='utf-8'))

    def accepted_task(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker')
        self.call('submit', 'T-1', '--actor', 'worker')
        self.call('review', 'T-1', '--reviewer', 'reviewer', '--result', 'pass',
                  '--check', 'PASS; command=fixture checks; result=exit 0; evidence=checked',
                  '--findings', 'passed', *self.fresh_context())

    def test_hidden_tracked_edits_invalidate_review_and_completion(self):
        self.accepted_task()
        path = self.root / 'tracked.txt'
        original = path.read_bytes()
        check = ('--check', 'PASS; command=fixture checks; result=exit 0; evidence=checked')
        for flag, clear_flag in (('--assume-unchanged', '--no-assume-unchanged'),
                                 ('--skip-worktree', '--no-skip-worktree')):
            with self.subTest(flag=flag):
                self.git('update-index', flag, 'tracked.txt')
                before = json.loads(self.call('snapshot', '--json').stdout)
                index_path = self.root / '.git' / 'index'
                index_bytes = index_path.read_bytes()
                tags = self.git('ls-files', '-v', '-z').stdout
                path.write_text('hidden edit\n', encoding='utf-8')
                self.assertNotIn('tracked.txt', self.git('status', '--porcelain').stdout)
                after = json.loads(self.call('snapshot', '--json').stdout)
                self.assertNotEqual(before['fingerprint'], after['fingerprint'])
                self.assertNotEqual(before['state_fingerprint'], after['state_fingerprint'])
                self.assertEqual(index_bytes, index_path.read_bytes())
                self.assertEqual(tags, self.git('ls-files', '-v', '-z').stdout)
                rejected = self.call('integrate', 'T-1', '--actor', 'director', *check, ok=False)
                self.assertIn('stale', rejected.stderr)
                path.write_bytes(original)
                self.git('update-index', clear_flag, 'tracked.txt')

        self.call('integrate', 'T-1', '--actor', 'director', *check)
        for flag, clear_flag in (('--assume-unchanged', '--no-assume-unchanged'),
                                 ('--skip-worktree', '--no-skip-worktree')):
            with self.subTest(completion_flag=flag):
                self.git('update-index', flag, 'tracked.txt')
                path.write_text('hidden completion edit\n', encoding='utf-8')
                rejected = self.call('complete', 'T-1', '--actor', 'director', *check, ok=False)
                self.assertIn('stale', rejected.stderr)
                self.assertEqual(self.db()['tasks']['T-1']['state'], 'integrated')
                path.write_bytes(original)
                self.git('update-index', clear_flag, 'tracked.txt')
        self.call('complete', 'T-1', '--actor', 'director', *check)

    def test_hooks_notice_hidden_tracked_edits_with_fresh_state_marker(self):
        hooks_source = SCRIPT.parents[1] / 'hooks'
        self.git('config', 'core.filemode', 'false')
        (self.root / '.gitignore').write_text('.codex/\n', encoding='utf-8')
        self.git('add', '.gitignore')
        self.git('commit', '-qm', 'ignore fixture state')
        helper_dir = self.root / '.codex' / 'hooks'
        helper_dir.mkdir()
        shutil.copyfile(SCRIPT, helper_dir / 'orchestrate.py')
        state = self.root / '.codex' / 'PROJECT_STATE.md'
        env = self.env.copy()
        env['SOL_DEEPSEEK_NUDGE_DIR'] = str(self.root.parent / 'nudges')
        for flag, clear_flag in (('--assume-unchanged', '--no-assume-unchanged'),
                                 ('--skip-worktree', '--no-skip-worktree')):
            with self.subTest(flag=flag):
                self.git('update-index', flag, 'tracked.txt')
                fingerprint = json.loads(self.call('snapshot', '--json').stdout)['state_fingerprint']
                state.write_text(f'state\n<!-- orchestrator-snapshot:{fingerprint} -->\n', encoding='utf-8')
                (self.root / 'tracked.txt').write_text('hidden hook edit\n', encoding='utf-8')
                self.assertEqual(self.git('status', '--porcelain').stdout, '')
                for hook, expected in (('inject_project_state.py', 'snapshot is stale'),
                                       ('stop_project_state_check.py', '"decision": "block"')):
                    result = subprocess.run([sys.executable, str(hooks_source / hook)],
                        cwd=self.root, env=env, text=True, capture_output=True,
                        input=json.dumps({'cwd': str(self.root), 'turn_id': flag}))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(expected, result.stdout)
                (self.root / 'tracked.txt').write_text('base\n', encoding='utf-8')
                self.git('update-index', clear_flag, 'tracked.txt')

    def test_repeated_permission_error_cannot_record_review_or_finish_task(self):
        self.accepted_task()
        spec = importlib.util.spec_from_file_location('runtime_denial_test', SCRIPT)
        runtime = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime)
        target = self.root / 'tracked.txt'
        real_read = Path.read_bytes
        def denied(path):
            if path == target:
                raise PermissionError('fixture read denied')
            return real_read(path)
        check = ('--check', 'PASS; command=fixture checks; result=exit 0; evidence=checked')
        def main(*args):
            return runtime.main(['--project', str(self.root), *args])
        ledger = self.root / '.codex' / 'ORCHESTRATOR.json'
        with mock.patch.dict(os.environ, self.env):
            for content in ('unreadable version one\n', 'unreadable version two\n'):
                target.write_text(content, encoding='utf-8')
                before = ledger.read_bytes()
                with mock.patch.object(Path, 'read_bytes', denied):
                    self.assertEqual(main('snapshot', '--json'), 2)
                    self.assertEqual(main('review', 'T-1', '--reviewer', 'another-reviewer',
                        '--result', 'pass', '--findings', 'passed', *check, *self.fresh_context()), 2)
                    self.assertEqual(main('integrate', 'T-1', '--actor', 'director', *check), 2)
                self.assertEqual(ledger.read_bytes(), before)
            target.write_text('base\n', encoding='utf-8')
            self.assertEqual(main('integrate', 'T-1', '--actor', 'director', *check), 0)
            target.write_text('unreadable completion content\n', encoding='utf-8')
            before = ledger.read_bytes()
            with mock.patch.object(Path, 'read_bytes', denied):
                self.assertEqual(main('complete', 'T-1', '--actor', 'director', *check), 2)
            self.assertEqual(ledger.read_bytes(), before)

    def test_recovery_invalidates_prior_pass_and_rechecks_reviewer_independence(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker-old', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker-old')
        (self.root / 'tracked.txt').write_text('implementation\n', encoding='utf-8')
        self.call('submit', 'T-1', '--actor', 'worker-old')
        pass_check = 'PASS; command=focused checks; result=exit 0; evidence=verified behavior'
        self.call('review', 'T-1', '--reviewer', 'reviewer-r', '--result', 'pass',
                  '--check', pass_check, '--findings', 'contract met', *self.fresh_context())

        # The reviewer pass is retained in history, but recovery changes the
        # author set and starts a new implementation attempt on the same tree.
        self.call('start', 'T-1', '--actor', 'worker-old')
        self.call('interrupt', 'T-1', '--actor', 'worker-old')
        self.call('recover', 'T-1', '--owner', 'reviewer-r', '--actor', 'director',
                  '--context', 'resume from preserved diff', '--old-agent-interrupted')
        self.call('start', 'T-1', '--actor', 'reviewer-r')
        self.call('submit', 'T-1', '--actor', 'reviewer-r')
        blocked = self.call(
            'integrate', 'T-1', '--actor', 'director',
            '--check', 'PASS; command=combined checks; result=exit 0; evidence=verified',
            ok=False,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn(self.db()['tasks']['T-1']['state'], {'ready_for_review', 'blocked'})
        task = self.db()['tasks']['T-1']
        self.assertEqual(len(task['evidence']), 1)
        self.assertEqual(task['evidence'][0]['reviewer'], 'reviewer-r')
        self.assertEqual(task['evidence'][0]['result'], 'pass')

    def test_start_after_pass_invalidates_acceptance_even_when_snapshot_is_unchanged(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker')
        self.call('submit', 'T-1', '--actor', 'worker')
        self.call('review', 'T-1', '--reviewer', 'reviewer-r', '--result', 'pass',
                  '--check', 'PASS; command=focused checks; result=exit 0; evidence=verified',
                  '--findings', 'passed', *self.fresh_context())
        first_attempt = self.db()['tasks']['T-1']['attempt']
        self.call('start', 'T-1', '--actor', 'worker')
        self.call('submit', 'T-1', '--actor', 'worker')
        task = self.db()['tasks']['T-1']
        self.assertGreater(task['attempt'], first_attempt)
        self.assertEqual(task['evidence'][-1]['result'], 'pass')  # retained for audit
        self.call('integrate', 'T-1', '--actor', 'director',
                  '--check', 'PASS; command=combined checks; result=exit 0; evidence=verified', ok=False)

    def test_contract_change_invalidates_plan_and_old_pass_without_changing_bytes(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker')
        self.call('submit', 'T-1', '--actor', 'worker')
        self.call('review', 'T-1', '--reviewer', 'reviewer-r', '--result', 'inconclusive',
                  '--findings', 'need contract clarification', *self.fresh_context())
        before = self.call('snapshot', '--json').stdout
        self.call('replan', 'T-1', '--actor', 'director', '--director', 'director',
                  '--reason', 'clarify observable contract', '--acceptance', 'new observable result')
        after = self.call('snapshot', '--json').stdout
        self.assertEqual(before, after)
        task = self.db()['tasks']['T-1']
        self.assertEqual(task['contract_revision'], 2)
        self.assertEqual(task['acceptance_plans'][0]['invalidated'], True)
        self.assertEqual(task['evidence'][-1]['result'], 'inconclusive')
        self.call('assign', 'T-1', '--owner', 'worker-new', '--actor', 'director', ok=False)

    def test_controlled_recovery_rejects_late_submission_by_previous_owner(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker-old', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker-old')
        self.call('interrupt', 'T-1', '--actor', 'worker-old')
        missing_stop = self.call('recover', 'T-1', '--owner', 'worker-new', '--actor', 'director',
                                 '--context', 'old worker explicitly stopped', ok=False)
        self.assertIn('not authentication or proof', missing_stop.stderr)
        self.call('recover', 'T-1', '--owner', 'worker-new', '--actor', 'director',
                  '--context', 'old worker explicitly stopped', '--old-agent-interrupted')
        rejected = self.call('submit', 'T-1', '--actor', 'worker-old', ok=False)
        self.assertIn('owner mismatch', rejected.stderr)
        self.call('start', 'T-1', '--actor', 'worker-new')

    def test_recovery_cannot_turn_current_acceptance_planner_into_task_author(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker-old', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker-old')
        self.call('interrupt', 'T-1', '--actor', 'worker-old')
        rejected = self.call('recover', 'T-1', '--owner', 'planner', '--actor', 'director',
                             '--context', 'resume task', '--old-agent-interrupted', ok=False)
        self.assertIn('acceptance planner cannot become', rejected.stderr)
        task = self.db()['tasks']['T-1']
        self.assertEqual(task['state'], 'interrupted')
        self.assertEqual(task['owner'], 'worker-old')

    def test_review_requires_explicit_fresh_context_and_inconclusive_is_retained(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker', '--actor', 'director')
        self.call('start', 'T-1', '--actor', 'worker')
        self.call('submit', 'T-1', '--actor', 'worker')
        missing = self.call('review', 'T-1', '--reviewer', 'reviewer-r', '--result', 'pass',
                            '--check', 'PASS; command=focused; result=exit 0; evidence=verified',
                            '--findings', 'passed', ok=False)
        self.assertIn('fresh-context manual attestation', missing.stderr)
        self.assertIn('not authentication', missing.stderr)
        self.call('review', 'T-1', '--reviewer', 'reviewer-r', '--result', 'inconclusive',
                  '--findings', 'unable to verify behavior', *self.fresh_context())
        task = self.db()['tasks']['T-1']
        self.assertEqual(task['state'], 'blocked')
        self.assertEqual(task['evidence'][-1]['result'], 'inconclusive')
        self.call('integrate', 'T-1', '--actor', 'director',
                  '--check', 'PASS; command=combined; result=exit 0; evidence=verified', ok=False)

    def test_high_risk_verification_uses_read_only_sol_reviewer_not_sol_senior(self):
        self.add('T-HIGH', risk='high')
        self.plan('T-HIGH', reviewer='planner')
        self.call('assign', 'T-HIGH', '--owner', 'worker', '--actor', 'director')
        self.call('start', 'T-HIGH', '--actor', 'worker')
        self.call('submit', 'T-HIGH', '--actor', 'worker')
        review = ('review', 'T-HIGH', '--reviewer', 'luna-reviewer', '--result', 'pass',
                  '--check', 'PASS; command=security; result=exit 0; evidence=verified',
                  '--findings', 'verified', *self.fresh_context())
        rejected = self.call(*review, '--senior-verified', '--senior-reviewer', 'sol-reviewer',
                             '--senior-role', 'sol_senior', ok=False)
        self.assertIn('invalid choice', rejected.stderr)
        self.call(*review, '--senior-verified', '--senior-reviewer', 'sol-reviewer',
                  '--senior-role', 'sol_reviewer')
        evidence = self.db()['tasks']['T-HIGH']['evidence'][-1]['senior_verifier']
        self.assertEqual(evidence['role'], 'sol_reviewer')
        self.assertEqual(evidence['model'], 'gpt-6.1-sol')
        self.assertTrue(evidence['read_only'])

    def test_replan_cannot_revoke_an_assignment_while_worker_may_still_run(self):
        self.add()
        self.plan('T-1', reviewer='planner')
        self.call('assign', 'T-1', '--owner', 'worker-old', '--actor', 'director')
        result = self.call(
            'replan', 'T-1', '--actor', 'director', '--director', 'director',
            '--reason', 'change scope', '--scope', 'other.txt', ok=False,
        )
        self.assertIn('replan requires planned or blocked state', result.stderr)
        task = self.db()['tasks']['T-1']
        self.assertEqual(task['state'], 'assigned')
        self.assertEqual(task['owner'], 'worker-old')
        self.call('submit', 'T-1', '--actor', 'worker-old', ok=False)

    @unittest.skipUnless(os.name == 'posix', 'POSIX executable-bit regression')
    def test_snapshot_changes_for_mode_change_on_an_already_dirty_file(self):
        path = self.root / 'tracked.txt'
        path.write_text('modified content\n', encoding='utf-8')
        path.chmod(0o644)
        before = json.loads(self.call('snapshot', '--json').stdout)
        path.chmod(0o755)
        after = json.loads(self.call('snapshot', '--json').stdout)
        self.assertNotEqual(before['fingerprint'], after['fingerprint'])

    def test_snapshot_tracks_dirty_submodule_or_fails_closed(self):
        blob = self.git('hash-object', '-w', '--stdin', input='gitlink fixture\n').stdout.strip()
        self.git('update-index', '--add', '--cacheinfo', f'160000,{blob},vendor/nested')
        rejected = self.call('snapshot', '--json', ok=False)
        self.assertIn('gitlink/submodule snapshot is unsupported', rejected.stderr)
        self.git('commit', '-qm', 'commit gitlink fixture')
        self.git('update-index', '--force-remove', 'vendor/nested')
        rejected_head = self.call('snapshot', '--json', ok=False)
        self.assertIn('gitlink/submodule snapshot is unsupported', rejected_head.stderr)

    @unittest.skipUnless(os.name == 'posix', 'literal backslash filenames are POSIX-specific')
    def test_snapshot_preserves_literal_backslash_path_without_reading_outside_root(self):
        outside = self.root.parent / 'outside.txt'
        inside = self.root / r'..\outside.txt'
        outside.write_text('outside version one\n', encoding='utf-8')
        inside.write_text('inside version one\n', encoding='utf-8')
        first = json.loads(self.call('snapshot', '--json').stdout)
        self.assertIn(r'..\outside.txt', first['paths'])

        outside.write_text('outside version two\n', encoding='utf-8')
        second = json.loads(self.call('snapshot', '--json').stdout)
        self.assertEqual(first['fingerprint'], second['fingerprint'])

        inside.write_text('inside version two\n', encoding='utf-8')
        third = json.loads(self.call('snapshot', '--json').stdout)
        self.assertNotEqual(second['fingerprint'], third['fingerprint'])

    def test_significant_task_requires_preimplementation_acceptance_plan_and_fresh_context_record(self):
        self.add('T-PLAN', scope='src/**', risk='high')
        assignment = self.call(
            'assign', 'T-PLAN', '--owner', 'worker', '--actor', 'director', ok=False,
        )
        self.assertIn('plan', assignment.stderr.lower())

        # The plan is a manual record. It must state the contract/scenarios and
        # attest that a new review context received the contract, diff, relevant
        # code, and verifiable results; an agent name alone is insufficient.
        self.call(
            'plan-review', 'T-PLAN', '--actor', 'director', '--director', 'director', '--reviewer', 'reviewer-fresh',
            '--contract-version', '1', '--scenario', 'permission denied returns 403',
            '--fresh-context-attested', '--context-item', 'contract',
            '--context-item', 'diff', '--context-item', 'relevant-code',
            '--context-item', 'verification-results',
        )
        plan = self.db()['tasks']['T-PLAN']['acceptance_plans'][-1]
        self.assertEqual(plan['reviewer'], 'reviewer-fresh')
        self.assertEqual(set(plan['context_items']), {
            'contract', 'diff', 'relevant-code', 'verification-results',
        })
        self.assertEqual(plan['status'], 'planned')

    def test_acceptance_plan_rejects_missing_fresh_context_items(self):
        self.add('T-PLAN', risk='medium')
        rejected = self.call(
            'plan-review', 'T-PLAN', '--actor', 'director', '--director', 'director',
            '--reviewer', 'reviewer-fresh', '--contract-version', '1',
            '--scenario', 'response is observable', '--fresh-context-attested',
            '--context-item', 'contract', ok=False,
        )
        self.assertIn('fresh-context manual attestation', rejected.stderr)
        self.call('assign', 'T-PLAN', '--owner', 'worker', '--actor', 'director', ok=False)

    def fresh_context(self):
        return ('--fresh-context-attested', '--context-item', 'contract', '--context-item', 'diff',
                '--context-item', 'relevant-code', '--context-item', 'verification-results')

    def plan(self, tid, reviewer):
        self.call('plan-review', tid, '--actor', 'director', '--director', 'director',
                  '--reviewer', reviewer, '--contract-version', '1',
                  '--scenario', 'observable behavior', '--fresh-context-attested',
                  '--context-item', 'contract', '--context-item', 'diff',
                  '--context-item', 'relevant-code', '--context-item', 'verification-results')


if __name__ == '__main__':
    unittest.main()
