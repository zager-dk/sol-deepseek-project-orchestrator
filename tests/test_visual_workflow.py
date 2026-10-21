"""Synthetic ledger fixtures, not live image inspection or model dispatch tests."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'orchestrate.py'
PASS = 'PASS; command=fixture; result=exit 0; evidence=synthetic ledger test'
CONTEXT = ['--fresh-context-attested', '--context-item', 'contract', '--context-item', 'diff',
           '--context-item', 'relevant-code', '--context-item', 'verification-results']
CAPABILITIES = ['reference_search', 'image_inspection', 'editable_export', 'preview_export',
                'custom_roles', 'image_generation', 'video_generation', 'browser_interaction', 'temporal_inspection']


class VisualWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.base = Path(self.tmp.name)
        self.root = self.base / 'project'; self.root.mkdir()
        self.env = os.environ.copy()
        self.env.update({'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull})
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, env=self.env)
        tree = subprocess.run(['git', 'mktree'], cwd=self.root, env=self.env, input='', text=True, capture_output=True, check=True).stdout.strip()
        (self.root / '.git/HEAD').write_text(tree)
        self.cli('init')
        for name in ('board-a.svg', 'board-b.svg', 'prototype.svg', 'final.svg', 'source.svg', 'report.txt'):
            (self.root / name).write_text('<svg xmlns="http://www.w3.org/2000/svg"><rect width="10" height="10"/></svg>' if name.endswith('.svg') else 'Synthetic test report')
        self.spec = {
            'brief': {'idea': 'Fixture card', 'audience': 'Test operators', 'constraints': ['No external publishing']},
            'references': [{'id': 'ref', 'url': 'https://www.w3.org/WAI/', 'take': 'Readable hierarchy',
                            'avoid': 'Copying branding', 'inspection_source': 'synthetic fixture, not a real observation', 'kind': 'motion'}],
            'directions': [{'id': name, 'summary': 'Coherent fixture direction ' + name,
                            'palette': ['#112233', '#FFFFFF'], 'reference_ids': ['ref'],
                            'motion_reference_ids': ['ref'], 'board': {'path': 'board-' + name + '.svg', 'format': 'svg'}} for name in ('a', 'b')],
            'deliverables': {'editable': ['svg'], 'preview': ['svg'], 'report': ['txt']},
            'required_capabilities': []}
        self.capabilities = {'capabilities': {name: {'status': 'available', 'tool': 'fixture-only',
            'source': 'test:synthetic', 'evidence': 'Synthetic test observation, not live capability discovery'} for name in CAPABILITIES}}
        self.approval = {'decision': 'approved', 'origin': 'user', 'approved_by': 'test-user',
                         'source': 'test:synthetic-user-message', 'quote': 'Synthetic explicit approval'}

    def tearDown(self): self.tmp.cleanup()

    def cli(self, *args, ok=True):
        result = subprocess.run([sys.executable, '-B', str(SCRIPT), '--project', str(self.root), *args],
                                cwd=self.root, env=self.env, text=True, capture_output=True)
        if ok and result.returncode: self.fail(f'{args}\n{result.stderr}')
        if not ok and result.returncode == 0: self.fail(f'expected rejection: {args}')
        if not ok: self.assertNotIn('Traceback', result.stderr)
        return result

    def record(self, cmd, data, *args, actor='director', ok=True):
        file = self.base / 'input.json'; file.write_text(json.dumps(data))
        return self.cli(cmd, 'A', '--actor', actor, '--file', str(file), *args, ok=ok)

    def task(self): return json.loads((self.root / '.codex/ORCHESTRATOR.json').read_text())['tasks']['A']

    def add(self, profile='visual-design'):
        self.profile = profile
        self.cli('add', 'A', '--profile', profile, '--goal', 'fixture', '--scope', '*', '--risk', 'low',
                 '--acceptance', 'Visual workflow gates and checked deliverables', '--actor', 'director')
        self.cli('plan-review', 'A', '--actor', 'director', '--director', 'director', '--reviewer', 'reviewer',
                 '--contract-version', '1', '--scenario', 'Synthetic profile gates', *CONTEXT)
        self.cli('assign', 'A', '--owner', 'worker', '--actor', 'director', '--owner-role', 'luna_worker')
        self.cli('start', 'A', '--actor', 'worker')

    def directions(self, profile='visual-design'):
        self.add(profile)
        if profile == 'motion-fx': self.spec['deliverables']['preview'] = ['webm']
        self.record('visual-spec', self.spec)
        self.record('visual-preflight', self.capabilities)

    def direction_approval(self):
        self.record('visual-approve', {**self.approval, 'revision': self.task()['visual']['revision'],
            'direction_id': 'a', 'palette': ['#112233', '#FFFFFF']}, '--target', 'direction')

    def preview(self, path):
        value = {'role': 'preview', 'path': path, 'format': 'svg', 'kind': 'image'}
        if self.profile == 'motion-fx':
            clip = str(Path(path).with_suffix('.webm')); (self.root / clip).write_bytes(b'Synthetic ledger fixture, not a playable video')
            value.update({'path':clip, 'format':'webm', 'kind': 'video', 'duration_seconds': 2})
        return value

    def prototype(self):
        self.direction_approval()
        self.record('visual-artifacts', {'artifacts': [self.preview('prototype.svg')]}, '--target', 'prototype', actor='worker')
        self.record('visual-approve', {**self.approval, 'revision': self.task()['visual']['revision'],
            'finished_slice': {k:{'result':'pass','tool':'fixture','source':'synthetic','observation':'Synthetic actual observation'} for k in ('keyframe','reference_comparison','main_flow')},
            'artifact_digest': self.task()['visual']['prototype_digest']}, '--target', 'prototype')

    def production(self, profile='visual-design'):
        self.directions(profile); self.prototype()
        self.cli('visual-production', 'A', '--actor', 'director')
        self.record('visual-artifacts', {'artifacts': [self.preview('final.svg'),
            {'role': 'editable', 'path': 'source.svg', 'format': 'svg'},
            {'role': 'report', 'path': 'report.txt', 'format': 'txt'}]}, '--target', 'final', actor='worker')
        self.cli('submit', 'A', '--actor', 'worker')

    def qa(self):
        preview = next(x for x in self.task()['visual']['artifacts'] if x['role'] == 'preview')
        opened = {'path': preview['path'], 'content': preview['content'], 'tool': 'fixture',
                  'source': 'test:synthetic-inspection', 'observation': 'Synthetic visible hierarchy result'}
        checks = ['visual', 'palette', 'references', 'editable_source']
        if self.profile == 'ux-ui': checks += ['interactions', 'responsive', 'accessibility']
        if self.profile == 'storyboard': checks += ['sequence', 'continuity']
        if self.profile == 'motion-fx':
            checks += ['timing', 'transitions', 'continuity']
            opened.update({'mode': 'playback', 'start_seconds': 0, 'end_seconds': 2})
        return {'reviewer': 'reviewer', 'result': 'pass', 'findings': 'Synthetic fixture only', 'unrun': [],
                'opened': [opened], 'checks': {x: {'result': 'pass', 'tool': 'fixture', 'source': 'test:synthetic',
                'evidence': 'Synthetic assertion'} for x in checks}}

    def general_review(self, ok=True):
        return self.cli('review', 'A', '--reviewer', 'reviewer', '--reviewer-role', 'luna_reviewer',
                        '--result', 'pass', '--check', PASS, '--findings', 'Synthetic fixture', *CONTEXT, ok=ok)

    def test_static_ui_storyboard_motion_positive_lifecycle(self):
        # Each profile uses a fresh ledger; no real visual review is claimed.
        for profile in ('visual-design', 'ux-ui', 'storyboard', 'motion-fx'):
            with self.subTest(profile=profile):
                if (self.root / '.codex/ORCHESTRATOR.json').exists():
                    (self.root / '.codex/ORCHESTRATOR.json').unlink(); self.cli('init')
                self.production(profile)
                self.record('visual-qa', self.qa(), actor='reviewer')
                self.general_review(); self.cli('integrate', 'A', '--actor', 'director', '--check', PASS)
                self.cli('complete', 'A', '--actor', 'director', '--check', PASS)
                self.assertEqual(self.task()['state'], 'completed')

    def test_no_manual_control_visual_opt_out(self):
        result = self.cli('add', 'A', '--profile', 'ux-ui', '--review-mode', 'manual-control', '--risk', 'low',
                 '--goal', 'x', '--scope', '*', '--acceptance', 'x', '--actor', 'director', ok=False)
        self.assertIn('independent acceptance', result.stderr)

    def test_cannot_produce_or_submit_without_spec_and_both_approvals(self):
        self.add()
        self.cli('visual-production', 'A', '--actor', 'director', ok=False)
        self.cli('submit', 'A', '--actor', 'worker', ok=False)
        self.record('visual-spec', self.spec); self.record('visual-preflight', self.capabilities)
        self.cli('visual-production', 'A', '--actor', 'director', ok=False)
        self.direction_approval()
        self.cli('visual-production', 'A', '--actor', 'director', ok=False)
        self.record('visual-artifacts', {'artifacts': [self.preview('prototype.svg')]}, '--target', 'prototype', actor='worker')
        self.cli('visual-production', 'A', '--actor', 'director', ok=False)
        self.cli('submit', 'A', '--actor', 'worker', ok=False)

    def test_false_approval_and_stale_revision_palette_are_rejected(self):
        self.directions()
        good = {**self.approval, 'revision': 1, 'direction_id': 'a', 'palette': ['#112233', '#FFFFFF']}
        for change in ({'decision': 'PASS'}, {'origin': 'agent'}, {'source': ''}, {'quote': ''},
                       {'revision': True}, {'revision': 2}, {'palette': ['#000000']}):
            with self.subTest(change=change): self.record('visual-approve', {**good, **change}, '--target', 'direction', ok=False)
        self.assertEqual(self.task()['visual']['approvals'], {})

    def test_new_spec_invalidates_preflight_and_approvals(self):
        self.directions(); self.prototype()
        changed = copy.deepcopy(self.spec); changed['directions'][0]['palette'] = ['#FF0000']
        self.record('visual-spec', changed, '--reason', 'direction-change')
        self.assertEqual(self.task()['visual']['revision'], 2)
        self.assertEqual(self.task()['visual']['approvals'], {})
        self.cli('visual-production', 'A', '--actor', 'director', ok=False)
        self.assertEqual(len(self.task()['visual']['spec_history']), 1)

    def test_changed_board_or_prototype_cannot_reuse_approval(self):
        self.directions(); self.prototype()
        (self.root / 'prototype.svg').write_text('changed prototype')
        self.assertIn('stale', self.cli('visual-production', 'A', '--actor', 'director', ok=False).stderr)
        (self.root / 'board-a.svg').write_text('changed board')
        self.assertIn('stale', self.record('visual-preflight', self.capabilities, ok=False).stderr)

    def test_preflight_blocks_missing_capability_but_not_optional_generation(self):
        self.directions('motion-fx')
        blocked = copy.deepcopy(self.capabilities); blocked['capabilities']['temporal_inspection']['status'] = 'unavailable'
        self.record('visual-preflight', blocked)
        self.record('visual-approve', {**self.approval, 'revision': 1, 'direction_id': 'a',
                    'palette': ['#112233', '#FFFFFF']}, '--target', 'direction', ok=False)
        for capability in ('image_generation', 'video_generation'):
            self.capabilities['capabilities'][capability]['status'] = 'unavailable'
        self.record('visual-preflight', self.capabilities); self.prototype()
        self.cli('visual-production', 'A', '--actor', 'director')

    def test_removing_required_capability_or_format_needs_sourced_scope_approval(self):
        self.spec['required_capabilities'] = ['video_generation']
        self.spec['deliverables']['editable'].append('pdf')
        self.directions()
        reduced = copy.deepcopy(self.spec); reduced['required_capabilities'] = []
        reduced['deliverables']['editable'] = ['svg']
        self.record('visual-spec', reduced, ok=False)
        reduced['scope_reduction'] = {'description':'User agrees to omit generator and PDF',
            'removed':['video_generation','editable:pdf'], 'approval':self.approval}
        self.record('visual-spec', reduced, '--reason', 'capability-change')
        self.assertEqual(self.task()['visual']['revision'], 2)
        self.assertEqual(self.task()['visual']['approvals'], {})

    def test_only_director_can_record_user_approval(self):
        self.directions()
        self.record('visual-approve', {**self.approval, 'revision': 1, 'direction_id': 'a',
            'palette': ['#112233', '#FFFFFF']}, '--target', 'direction', actor='worker', ok=False)

    def test_plain_pass_does_not_replace_visual_qa(self):
        self.production(); self.general_review(ok=False)
        self.record('visual-qa', {'reviewer': 'reviewer', 'result': 'pass', 'findings': 'PASS', 'unrun': []}, actor='reviewer', ok=False)
        self.cli('integrate', 'A', '--actor', 'director', '--check', PASS, ok=False)
        self.cli('complete', 'A', '--actor', 'director', '--check', PASS, ok=False)

    def test_ui_requires_interaction_responsive_accessibility_and_opened_pixels(self):
        self.production('ux-ui')
        for check in ('interactions', 'responsive', 'accessibility'):
            qa = self.qa(); del qa['checks'][check]
            self.record('visual-qa', qa, actor='reviewer', ok=False)
        qa = self.qa(); qa['opened'][0]['content'] = 'wrong render'
        self.record('visual-qa', qa, actor='reviewer', ok=False)
        qa = self.qa(); qa['unrun'] = ['mobile breakpoint']
        self.record('visual-qa', qa, actor='reviewer', ok=False)

    def test_motion_requires_full_temporal_review(self):
        self.production('motion-fx')
        for change in ({'mode': 'static-frames'}, {'end_seconds': 1}, {'start_seconds': 1}, {'end_seconds': True}):
            qa = self.qa(); qa['opened'][0].update(change)
            self.record('visual-qa', qa, actor='reviewer', ok=False)
        qa = self.qa(); del qa['checks']['timing']
        self.record('visual-qa', qa, actor='reviewer', ok=False)

    def test_motion_rejects_static_preview_even_when_labelled_video(self):
        self.directions('motion-fx'); self.direction_approval()
        self.record('visual-artifacts', {'artifacts':[{'path':'prototype.svg','format':'svg','kind':'video','duration_seconds':2,'role':'preview'}]}, '--target', 'prototype', actor='worker', ok=False)

    def test_reviewer_cannot_be_author_or_director(self):
        self.production()
        for person in ('worker', 'director'):
            qa = self.qa(); qa['reviewer'] = person
            self.record('visual-qa', qa, actor=person, ok=False)

    def test_extra_failed_or_inconclusive_check_prevents_pass(self):
        self.production()
        for result in ('fail', 'inconclusive', 'unrun'):
            qa = self.qa(); qa['checks']['critical_layout_bug'] = {'result':result,'evidence':'Known failure','tool':'fixture','source':'test:fixture'}
            self.record('visual-qa', qa, actor='reviewer', ok=False)
            self.general_review(ok=False)
        self.assertNotIn('qa', self.task()['visual'])

    def test_empty_or_whitespace_qa_identity_is_rejected(self):
        self.production()
        for identity in ('', '   '):
            qa = self.qa(); qa['reviewer'] = identity
            self.record('visual-qa', qa, actor=identity, ok=False)

    def test_ignored_artifact_change_blocks_complete(self):
        (self.root / '.gitignore').write_text('final.svg\n')
        self.production(); self.record('visual-qa', self.qa(), actor='reviewer'); self.general_review()
        self.cli('integrate', 'A', '--actor', 'director', '--check', PASS)
        (self.root / 'final.svg').write_text('unreviewed ignored output')
        self.assertIn('stale', self.cli('complete', 'A', '--actor', 'director', '--check', PASS, ok=False).stderr)

    def test_new_qa_or_preflight_invalidates_general_review(self):
        self.production(); self.record('visual-qa', self.qa(), actor='reviewer'); self.general_review()
        self.record('visual-preflight', self.capabilities, '--reason', 'capability-change')
        self.cli('integrate', 'A', '--actor', 'director', '--check', PASS, ok=False)
        self.general_review(ok=False)

    def test_failed_inconclusive_qa_never_passes(self):
        self.production()
        for result in ('fail', 'inconclusive'):
            self.record('visual-qa', {'reviewer': 'reviewer', 'result': result, 'findings': 'Observed issue'}, actor='reviewer')
            self.general_review(ok=False)

    def test_recovery_invalidates_old_qa(self):
        self.production(); self.record('visual-qa', self.qa(), actor='reviewer')
        self.cli('start', 'A', '--actor', 'worker'); self.cli('interrupt', 'A', '--actor', 'worker')
        self.cli('recover', 'A', '--owner', 'new-worker', '--actor', 'director', '--context', 'fixture', '--old-agent-interrupted')
        self.cli('start', 'A', '--actor', 'new-worker'); self.cli('submit', 'A', '--actor', 'new-worker')
        self.general_review(ok=False)

    def test_contract_replan_invalidates_user_evidence(self):
        self.production()
        self.cli('review', 'A', '--reviewer', 'reviewer', '--result', 'inconclusive', '--findings', 'scope unclear', *CONTEXT)
        self.cli('replan', 'A', '--actor', 'director', '--director', 'director', '--reason', 'scope-change', '--acceptance', 'new acceptance')
        self.record('visual-approve', {**self.approval, 'revision': 1, 'finished_slice': {k:{'result':'pass','tool':'fixture','source':'synthetic','observation':'Synthetic actual observation'} for k in ('keyframe','reference_comparison','main_flow')},
            'artifact_digest': self.task()['visual']['prototype_digest']}, '--target', 'prototype', ok=False)

    def test_statistics_export_categories_not_private_evidence(self):
        self.production(); self.record('visual-qa', self.qa(), '--reason', 'qa-fix', actor='reviewer')
        report = json.loads(self.cli('stats').stdout)
        self.assertEqual(report['visual']['profiles'], {'visual-design': 1})
        self.assertIn('qa-fix', json.dumps(report['visual']))
        for private in ('Synthetic explicit approval', 'test:synthetic', 'final.svg'):
            self.assertNotIn(private, json.dumps(report))
        self.assertIsNone(report['visual']['observed_model']); self.assertIsNone(report['visual']['observed_tokens'])

    def test_existing_style_requires_version_and_user_source(self):
        self.add(); self.spec['directions'] = self.spec['directions'][:1]
        self.record('visual-spec', self.spec, ok=False)
        self.spec['existing_style'] = {'source': 'project:brand', 'version': 'v1', 'scope': 'fixture', 'approval': self.approval}
        self.record('visual-spec', self.spec)
        self.spec['existing_style']['approval'] = {'decision': 'approved'}
        self.record('visual-spec', self.spec, ok=False)

    def test_installed_visual_templates_and_runtime_are_self_contained(self):
        source = SCRIPT.parents[1]
        codex_home = self.base / 'isolated-codex'
        install = subprocess.run([sys.executable, str(source / 'scripts/install.py'), '--project', str(self.root),
                                  '--codex-home', str(codex_home), '--hooks'], env=self.env, capture_output=True, text=True)
        self.assertEqual(install.returncode, 0, install.stderr)
        skill = codex_home / 'skills/sol-deepseek-project-orchestrator'
        for filename in ('static-spec.json', 'ui-spec.json', 'capability-preflight.json', 'approval-template.json',
                         'qa-template.json', 'board-a.svg', 'board-b.svg', 'ui-prototype.html'):
            self.assertTrue((skill / 'examples/visual' / filename).is_file(), filename)
        for helper in (skill / 'scripts/orchestrate.py', self.root / '.codex/hooks/orchestrate.py'):
            result = subprocess.run([sys.executable, str(helper), '--help'], env=self.env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('visual-production', result.stdout)
        guide = skill / 'references/VISUAL_WORKFLOW.md'
        self.assertTrue(guide.is_file())
        self.assertNotIn('../../examples/visual', guide.read_text())

    def test_artifact_path_traversal_and_missing_formats_rejected(self):
        self.directions(); self.prototype(); self.cli('visual-production', 'A', '--actor', 'director')
        self.record('visual-artifacts', {'artifacts': [self.preview('final.svg')]}, '--target', 'final', actor='worker', ok=False)
        bad = self.preview('../input.json')
        self.record('visual-artifacts', {'artifacts': [bad]}, '--target', 'final', actor='worker', ok=False)


if __name__ == '__main__': unittest.main()
