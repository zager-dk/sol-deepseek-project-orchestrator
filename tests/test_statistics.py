import csv
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest import mock


SCRIPT = pathlib.Path(__file__).parents[1] / 'scripts' / 'orchestrate.py'
SPEC = importlib.util.spec_from_file_location('orchestrate_stats', SCRIPT)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
CONTEXT = ['contract', 'diff', 'relevant-code', 'verification-results']
PASS = 'PASS; command=focused; result=exit 0; evidence=assertions passed'


class LedgerFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='stats-project-', dir=tempfile.gettempdir())
        self.root = pathlib.Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q'], cwd=self.root, check=True)
        tree = subprocess.run(['git', 'mktree'], cwd=self.root, input='', text=True, capture_output=True, check=True).stdout.strip()
        (self.root / '.git' / 'HEAD').write_text(tree, encoding='ascii')

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, check=True):
        p = subprocess.run([os.environ.get('PYTHON', sys.executable), '-B', str(SCRIPT), '--project', str(self.root), *map(str, args)], text=True, capture_output=True)
        if check and p.returncode:
            self.fail(f'command failed ({p.returncode}): {args}\nstdout={p.stdout}\nstderr={p.stderr}')
        return p

    def initialize(self):
        self.cli('init')

    def ledger_path(self):
        return self.root / '.codex' / 'ORCHESTRATOR.json'

    def ledger(self):
        return json.loads(self.ledger_path().read_text(encoding='utf-8'))

    def add_task(self, tid, actor='director', acceptance='tests pass'):
        self.cli('add', tid, '--goal', 'safe task', '--scope', 'src/file.py', '--acceptance', acceptance, '--actor', actor, '--risk', 'low', '--review-mode', 'manual-control')


class StatisticsCliTests(LedgerFixture):
    def test_lifecycle_recovery_correction_and_real_json_csv_privacy(self):
        self.initialize()
        empty_csv=self.cli('stats','--format','csv').stdout
        empty_rows=list(csv.reader(io.StringIO(empty_csv,newline='')))
        self.assertEqual(len(empty_rows),1,repr(empty_csv)); self.assertEqual(empty_rows[0][:2],['schema','coverage'])
        original = self.ledger_path().read_bytes()
        self.assertNotEqual(self.cli('init', check=False).returncode, 0)
        self.assertEqual(self.ledger_path().read_bytes(), original)

        hostile = r'C:\Users\Private\secret.xlsx;=1+1'
        hostile_actor = 'actor\n=HYPERLINK("private")'
        self.add_task(hostile, actor=hostile_actor)
        before_duplicate = self.ledger_path().read_bytes()
        self.assertNotEqual(self.cli('add', hostile, '--goal', 'x', '--scope', 'src/file.py', '--acceptance', 'x', '--actor', 'dup', '--risk', 'low', '--review-mode', 'manual-control', check=False).returncode, 0)
        self.assertEqual(self.ledger_path().read_bytes(), before_duplicate)

        self.cli('assign', hostile, '--owner', 'worker-one', '--owner-role', 'luna_worker', '--actor', 'director')
        self.cli('start', hostile, '--actor', 'worker-one')
        self.cli('interrupt', hostile, '--actor', 'worker-one')
        self.cli('recover', hostile, '--owner', 'worker-two', '--owner-role', 'luna_worker', '--actor', 'director', '--context', 'resume', '--old-agent-interrupted')
        self.cli('start', hostile, '--actor', 'worker-two')
        self.cli('submit', hostile, '--actor', 'worker-two')
        ctx = sum((['--context-item', x] for x in CONTEXT), [])
        self.cli('review', hostile, '--reviewer', 'reviewer-one', '--reviewer-role', 'luna_reviewer', '--result', 'fail', '--findings', 'private failure detail', *ctx, '--fresh-context-attested')
        self.cli('submit', hostile, '--actor', 'worker-two')
        self.cli('review', hostile, '--reviewer', 'reviewer-two', '--reviewer-role', 'luna_reviewer', '--result', 'pass', '--check', PASS, '--findings', 'private success detail', *ctx, '--fresh-context-attested')
        self.cli('integrate', hostile, '--actor', 'director', '--check', PASS)
        self.cli('complete', hostile, '--actor', 'director', '--check', PASS)

        before_export=self.ledger_path().read_bytes()
        report = json.loads(self.cli('stats', '--format', 'json').stdout)
        self.assertEqual(report['coverage'], 'new_ledger')
        self.assertEqual(report['summary']['event_count'], len(report['events']))
        events = report['events']
        self.assertEqual([e['seq'] for e in events], list(range(1, len(events) + 1)))
        self.assertIn('recovered', [e['event'] for e in events])
        self.assertIn('review_fail', [e['event'] for e in events])
        self.assertEqual(events[1]['requested_role'], 'luna_worker')
        self.assertEqual(events[1]['from_state'], 'planned')
        self.assertEqual(events[1]['canonical_model'], 'gpt-6-luna')
        self.assertIsNone(events[1]['observed_model'])
        csv_text = self.cli('stats', '--format', 'csv').stdout
        rows = list(csv.DictReader(io.StringIO(csv_text, newline='')))
        self.assertEqual(len(rows), len(events))
        self.assertEqual(list(rows[0])[2:], module.STAT_KEYS)
        self.assertEqual([row['event'] for row in rows], [event['event'] for event in events])
        self.assertEqual(rows[0]['observed_model'],'')
        for row,event in zip(rows,events):
            for key in module.STAT_KEYS:
                self.assertEqual(row[key], '' if event[key] is None else str(event[key]))
        self.assertEqual(self.ledger_path().read_bytes(),before_export)
        combined = report.__repr__() + csv_text
        for secret in (hostile, hostile_actor, 'private failure detail', 'private success detail'):
            self.assertNotIn(secret, combined)
        self.assertEqual(events[0]['task_ref'], hashlib.sha256(b'orchestrator.stats.v1.task\0' + hostile.encode()).hexdigest())

    def test_legacy_boundary_replan_and_rejected_mutation(self):
        self.initialize()
        db = self.ledger()
        del db['statistics']
        self.ledger_path().write_text(json.dumps(db), encoding='utf-8')
        raw_before = self.ledger_path().read_bytes()
        legacy_report = json.loads(self.cli('stats', '--format', 'json').stdout)
        self.assertEqual(legacy_report['coverage'], 'not_started')
        self.assertEqual(self.ledger_path().read_bytes(), raw_before)
        self.add_task('replan-me')
        events = self.ledger()['statistics']['events']
        self.assertEqual(self.ledger()['statistics']['coverage'], 'legacy_partial')
        self.assertEqual([e['event'] for e in events], ['created'])
        before = self.ledger_path().read_bytes()
        self.assertNotEqual(self.cli('replan', 'replan-me', '--actor', 'wrong', '--director', 'director', '--reason', 'text', check=False).returncode, 0)
        self.assertEqual(self.ledger_path().read_bytes(), before)
        self.cli('replan', 'replan-me', '--actor', 'director', '--director', 'director', '--reason', 'private rationale', '--acceptance', 'new contract')
        report = json.loads(self.cli('stats').stdout)
        self.assertEqual([e['event'] for e in report['events']], ['created', 'replanned'])
        self.assertNotIn('private rationale', json.dumps(report))
        db=self.ledger(); db['statistics']=None; self.ledger_path().write_text(json.dumps(db),encoding='utf-8')
        before_null=self.ledger_path().read_bytes()
        for fmt in ('json','csv'):
            bad=self.cli('stats','--format',fmt,check=False)
            self.assertNotEqual(bad.returncode,0); self.assertEqual(bad.stdout,'')
        self.assertNotEqual(self.cli('replan','replan-me','--actor','director','--director','director','--reason','x',check=False).returncode,0)
        self.assertEqual(self.ledger_path().read_bytes(),before_null)
        db=self.ledger(); db['statistics']={'schema':999,'coverage':'new_ledger','events':[]}; self.ledger_path().write_text(json.dumps(db),encoding='utf-8')
        for fmt in ('json','csv'):
            bad=self.cli('stats','--format',fmt,check=False)
            self.assertNotEqual(bad.returncode,0); self.assertEqual(bad.stdout,'')

    def test_cli_invalid_event_state_clock_matrix_fails_closed(self):
        self.initialize(); self.add_task('bad-matrix')
        ctx=sum((['--context-item',x] for x in CONTEXT),[])
        self.cli('plan-review','bad-matrix','--actor','director','--director','director','--reviewer','reader','--contract-version','1','--scenario','check valid event states',*ctx,'--fresh-context-attested')
        valid=json.loads(self.ledger_path().read_text(encoding='utf-8'))
        self.assertIsNone(valid['statistics']['events'][0]['elapsed_ms'])
        self.assertEqual((valid['statistics']['events'][0]['from_state'],valid['statistics']['events'][0]['to_state']),(None,'planned'))
        self.assertEqual((valid['statistics']['events'][1]['from_state'],valid['statistics']['events'][1]['to_state']),('planned','planned'))
        cases=(
            lambda x: x[0].update(elapsed_ms=7),
            lambda x: x[0].update(to_state='completed'),
            lambda x: x[1].update(elapsed_ms=7),
            lambda x: x[1].update(event='assigned'),
            lambda x: x[0].update(clock_anomaly='backward_clock'),
            lambda x: x[0].update(from_state='planned'),
        )
        for corrupt in cases:
            bad=json.loads(json.dumps(valid)); corrupt(bad['statistics']['events'])
            raw=json.dumps(bad,ensure_ascii=False).encode('utf-8')+b'\n'
            self.ledger_path().write_bytes(raw)
            for fmt in ('json','csv'):
                exported=self.cli('stats','--format',fmt,check=False)
                self.assertNotEqual(exported.returncode,0); self.assertEqual(exported.stdout,'')
            mutated=self.cli('replan','bad-matrix','--actor','director','--director','director','--reason','must not publish',check=False)
            self.assertNotEqual(mutated.returncode,0); self.assertEqual(mutated.stdout,'')
            self.assertEqual(self.ledger_path().read_bytes(),raw)
        self.ledger_path().write_bytes(json.dumps(valid,ensure_ascii=False).encode('utf-8')+b'\n')
        self.assertEqual(len(json.loads(self.cli('stats').stdout)['events']),2)

    def test_legacy_start_uses_real_prior_state(self):
        self.initialize()
        db=self.ledger(); del db['statistics']
        db['tasks']['old']={'id':'old','goal':'g','depends_on':[],'priority':1,'risk':'low','scope':['src/a.py'],'acceptance':'a','contract_revision':1,'review_mode':'manual-control','owner':'legacy-owner','owner_history':['legacy-owner'],'attempt':0,'state':'assigned','review_rounds':0,'consultations':0,'evidence':[],'snapshot':None}
        self.ledger_path().write_text(json.dumps(db),encoding='utf-8')
        self.cli('start','old','--actor','legacy-owner')
        event=json.loads(self.cli('stats').stdout)['events'][0]
        self.assertEqual((event['event'],event['from_state'],event['to_state'],event['attempt']),('in_progress','assigned','in_progress',1))
        self.assertEqual(event['clock_anomaly'],'missing_stage_timestamp')

    def test_legacy_assign_recover_and_start_record_actual_states(self):
        self.initialize(); db=self.ledger(); del db['statistics']
        common={'goal':'g','depends_on':[],'priority':1,'risk':'low','acceptance':'a','contract_revision':1,'review_mode':'manual-control','review_rounds':0,'consultations':0,'evidence':[],'snapshot':None}
        db['tasks']['planned']={**common,'id':'planned','scope':['src/one.py'],'owner':None,'owner_history':[],'attempt':0,'state':'planned'}
        db['tasks']['paused']={**common,'id':'paused','scope':['src/two.py'],'owner':'old','owner_history':['old'],'attempt':2,'state':'interrupted'}
        self.ledger_path().write_text(json.dumps(db),encoding='utf-8')
        self.cli('assign','planned','--owner','worker-a','--actor','director')
        self.cli('recover','paused','--owner','worker-b','--actor','director','--context','resume','--old-agent-interrupted')
        self.cli('start','planned','--actor','worker-a')
        self.cli('start','paused','--actor','worker-b')
        events=json.loads(self.cli('stats').stdout)['events']
        self.assertEqual([(e['event'],e['from_state']) for e in events],[('assigned','planned'),('recovered','interrupted'),('in_progress','assigned'),('in_progress','assigned')])
        self.assertIsNone(events[0]['requested_role']); self.assertIsNone(events[0]['canonical_effort'])

    def test_escalation_event_and_role_fields(self):
        self.initialize(); self.add_task('escalate-me')
        self.cli('assign', 'escalate-me', '--owner', 'luna', '--owner-role', 'luna_worker', '--actor', 'director')
        for n in (1, 2):
            if n == 1: self.cli('start', 'escalate-me', '--actor', 'luna')
            self.cli('submit', 'escalate-me', '--actor', 'luna')
            ctx = sum((['--context-item', x] for x in CONTEXT), [])
            self.cli('review', 'escalate-me', '--reviewer', f'reviewer-{n}', '--result', 'fail', '--findings', 'failure', *ctx, '--fresh-context-attested')
        self.cli('escalate', 'escalate-me', '--actor', 'director', '--director', 'director', '--owner', 'senior', '--owner-role', 'sol_senior', '--reason', 'repro', '--context', 'prior attempts', '--old-agent-interrupted')
        events = json.loads(self.cli('stats').stdout)['events']
        escalation = next(e for e in events if e['event'] == 'escalated')
        self.assertEqual((escalation['requested_role'], escalation['canonical_model'], escalation['canonical_effort']), ('sol_senior','gpt-6.1-sol','high'))
        self.assertIsNotNone(escalation['previous_participant_ref'])

    def test_snapshot_excludes_only_exact_bookkeeping_paths(self):
        self.initialize()
        clean=json.loads(self.cli('snapshot','--json').stdout)
        self.assertEqual(clean['paths'],[])
        lookalikes=['.codex/ORCHESTRATOR.json.export','.codex/ORCHESTRATOR_STORAGE.json.backup','.orchestrator-install-registry.json']
        for name in lookalikes:
            path=self.root/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text('visible',encoding='utf-8')
        visible=json.loads(self.cli('snapshot','--json').stdout)
        self.assertEqual(set(visible['paths']),set(lookalikes))

    def test_concurrent_writers_and_readers_observe_complete_sequences(self):
        self.initialize()
        errors=[]; snapshots=[]; stop=threading.Event()
        def writer(i):
            args=('add',f'parallel-{i}','--goal','g','--scope',f'src/{i}.py','--acceptance','a','--actor',f'actor-{i}','--risk','low','--review-mode','manual-control')
            for _ in range(600):
                p=self.cli(*args,check=False)
                if p.returncode==0: return
                if 'lock exists' not in p.stderr: errors.append(p.stderr); return
                time.sleep(.01)
            errors.append('writer exhausted lock retries')
        def reader():
            while not stop.is_set():
                p=self.cli('stats',check=False)
                try:
                    if p.returncode: raise AssertionError(p.stderr)
                    data=json.loads(p.stdout)
                    seq=[e['seq'] for e in data['events']]
                    if seq!=list(range(1,len(seq)+1)): raise AssertionError('non-contiguous sequence')
                    snapshots.append(len(seq))
                except Exception as exc: errors.append(str(exc)); return
        rt=threading.Thread(target=reader); rt.start()
        with ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(writer,range(12)))
        stop.set(); rt.join(timeout=10)
        self.assertFalse(rt.is_alive())
        self.assertEqual(errors,[])
        events=json.loads(self.cli('stats').stdout)['events']
        self.assertEqual(len(events),12)
        self.assertEqual([e['seq'] for e in events],list(range(1,13)))
        self.assertTrue(snapshots)


class StatisticsUnitTests(unittest.TestCase):
    def test_unchanged_events_do_not_reset_stage_duration(self):
        db=module.empty_db(); task={'id':'stage','state':'planned','attempt':0,'contract_revision':1,'review_rounds':0}
        with mock.patch.object(module.time,'time',side_effect=[0.5,1.0,5.0,6.0,7.0,8.0,9.0]):
            module.log(db,task,'created','director')
            module.log(db,task,'acceptance_plan_recorded','director',_stats_from_state='planned')
            task['state']='assigned'; module.log(db,task,'assigned','director',_stats_from_state='planned')
            task['state']='in_progress'; task['attempt']=1; module.log(db,task,'in_progress','worker',_stats_from_state='assigned')
            task['state']='ready_for_review'; module.log(db,task,'ready_for_review','worker',_stats_from_state='in_progress')
            task['review_rounds']=1; module.log(db,task,'review_pass','reviewer',checks=[PASS],_stats_from_state='ready_for_review')
            task['state']='integrated'; module.log(db,task,'integrated','director',checks=[PASS],_stats_from_state='ready_for_review')
        events=db['statistics']['events']
        self.assertIsNone(events[0]['elapsed_ms']); self.assertIsNone(events[1]['elapsed_ms']); self.assertIsNone(events[5]['elapsed_ms'])
        self.assertEqual(events[2]['elapsed_ms'],4500)
        self.assertEqual(events[3]['elapsed_ms'],1000)
        self.assertEqual(events[6]['elapsed_ms'],2000)
        malformed=json.loads(json.dumps(db['statistics']))
        malformed['events'][6]['elapsed_ms']+=1
        with self.assertRaises(module.OrchestrationError): module.validate_statistics(malformed)

    def test_closed_schema_nullable_and_bool_validation(self):
        db = module.empty_db()
        task = {'id':'t','state':'planned','attempt':0,'contract_revision':1,'review_rounds':0}
        module.log(db, task, 'created', 'a')
        for change in (
            lambda e: e.update(secret='private'),
            lambda e: e.update(seq=True),
            lambda e: e.update(attempt=True),
            lambda e: e.update(requested_role='luna_worker'),
            lambda e: e.update(observed_model='gpt-6-luna'),
            lambda e: e.update(actor_ref=None),
            lambda e: e.update(elapsed_ms='0'),
            lambda e: e.update(canonical_model='gpt-6-astra'),
        ):
            mutated = json.loads(json.dumps(db['statistics']))
            change(mutated['events'][0])
            with self.assertRaises(module.OrchestrationError):
                module.validate_statistics(mutated)
        with self.assertRaises(module.OrchestrationError):
            module.validate_statistics({'schema': True, 'coverage':'new_ledger', 'events':[]})
        with self.assertRaises(module.OrchestrationError):
            module.validate_statistics({'schema': 2, 'coverage':'new_ledger', 'events':[]})

    def test_clock_backward_invalid_and_missing_boundary(self):
        db = module.empty_db(); task={'id':'t','state':'assigned','attempt':0,'contract_revision':1,'review_rounds':0}
        with mock.patch.object(module.time, 'time', side_effect=[10.0, 9.0]):
            module.log(db,task,'assigned','a',_stats_from_state='planned'); task['state']='in_progress'; module.log(db,task,'in_progress','a',_stats_from_state='assigned')
        self.assertEqual(db['statistics']['events'][1]['clock_anomaly'],'backward_clock')
        db = module.empty_db(); task={'id':'u','state':'assigned','attempt':0,'contract_revision':1,'review_rounds':0}
        with mock.patch.object(module.time, 'time', side_effect=[float('inf'), 10.0]):
            module.log(db,task,'assigned','a',_stats_from_state='planned'); task['state']='in_progress'; module.log(db,task,'in_progress','a',_stats_from_state='assigned')
        self.assertEqual(db['statistics']['events'][0]['clock_anomaly'],'invalid_clock')
        self.assertEqual(db['statistics']['events'][1]['clock_anomaly'],'missing_stage_timestamp')

    def test_serialization_fsync_and_replace_failures_preserve_old_bytes(self):
        with tempfile.TemporaryDirectory(prefix='stats-save-', dir=tempfile.gettempdir()) as directory:
            root=pathlib.Path(directory); (root/'.codex').mkdir()
            module.ACTIVE_DATA_DIR=root/'.codex'
            path=root/'.codex'/'ORCHESTRATOR.json'; original=b'{"old":true}\n'; path.write_bytes(original)
            for patcher,db in (
                (mock.patch.object(module.json, 'dump', side_effect=TypeError('encode failure')), {'x':1}),
                (mock.patch.object(module.os, 'fsync', side_effect=OSError('sync failure')), {'x':1}),
                (mock.patch.object(module.os, 'replace', side_effect=OSError('replace failure')), {'x':1}),
            ):
                with patcher, self.assertRaises((OSError,TypeError)):
                    module.save(root,db)
                self.assertEqual(path.read_bytes(),original)
                self.assertFalse((path.parent/'ORCHESTRATOR.tmp').exists())


if __name__ == '__main__':
    unittest.main()
