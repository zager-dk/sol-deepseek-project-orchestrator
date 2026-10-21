"""Synthetic contract regressions; no real device or audio inspection claimed."""
import copy
import json
import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('readiness_runtime',Path(__file__).resolve().parents[1]/'scripts/orchestrate.py')
r=importlib.util.module_from_spec(spec); spec.loader.exec_module(r)

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.contract={'functional':['Main result works'],'user':['Goal achieved'],'target':'local CLI', 'checks':['python tool.py --help']}
        for key in ('visual','audio','performance','device'): self.contract[key]={'relevant':False,'reason':'Small nonvisual local task'}
        self.task={'id':'A','profile':'code','created_by':'director','owner_history':['worker'],'contract_revision':1,'attempt':1,'created_at':10,'state':'ready_for_review','acceptance':'Goal','readiness':self.contract}
    def evidence(self):
        checks={k:{'result':'not_applicable','reason':'Out of scope'} for k in ('visual','audio','performance','device')}
        checks.update({k:{'result':'pass','tool':'fixture','source':'synthetic','observation':'Observed fixture'} for k in ('functional','user')})
        return {'reviewer':'reviewer','snapshot':'abc','contract_revision':1,'attempt':1,'checks':checks}
    def test_small_nonvisual_contract_is_compact(self):
        self.assertEqual(r.readiness_contract(self.contract)['target'],'local CLI')
        r.require_readiness(self.task,self.evidence(),'reviewer',{'fingerprint':'abc'})
    def test_visual_prototype_needs_finished_slice_and_actual_comparison(self):
        self.task['profile']='ux-ui'
        with self.assertRaises(r.OrchestrationError): r.require_slice(self.task,{})
        early={k:{'result':'pass','tool':'fixture','source':'synthetic','observation':'Actual comparison'} for k in ('keyframe','main_flow','reference_comparison')}
        r.require_slice(self.task,{'finished_slice':early})
        del early['reference_comparison']
        with self.assertRaises(r.OrchestrationError): r.require_slice(self.task,{'finished_slice':early})
    def test_unavailable_audio_stays_not_verified(self):
        self.contract['audio']={'relevant':True,'criteria':'Audible completion feedback'}
        evidence=self.evidence(); evidence['checks']['audio']={'result':'not_verified','reason':'No listening tool available'}
        with self.assertRaisesRegex(r.OrchestrationError,'NOT VERIFIED'): r.require_readiness(self.task,evidence,'reviewer',{'fingerprint':'abc'})
        self.assertNotIn('readiness_evidence',self.task)
    def test_director_only_review_cannot_pass(self):
        evidence=self.evidence(); evidence['reviewer']='director'
        with self.assertRaises(r.OrchestrationError): r.require_readiness(self.task,evidence,'director',{'fingerprint':'abc'})
        observed={'origin':'observed','decision':'accepted','reviewer':'director','tool':'fixture','source':'fixture','observation':'Claim'}
        self.task['approval_mode']='observed'
        with self.assertRaises(r.OrchestrationError): r.selection_source(self.task,observed)
        observed.update({'reviewer':'reviewer','observer_origin':'independent-reviewer'})
        self.assertEqual(r.selection_source(self.task,observed)['origin'],'observed')
        observed['observer_origin']='director'
        with self.assertRaises(r.OrchestrationError): r.selection_source(self.task,observed)
    def test_repeat_same_criterion_requires_diagnosis(self):
        defect={'id':'D1','criterion':'main-flow','priority':'P1','reproduction':'Start fails','cause':'unknown, investigate','owner':'worker','status':'open'}
        r.record_defects(self.task,[defect]); self.assertFalse(self.task.get('diagnosis_required',False))
        r.record_defects(self.task,[{**defect,'id':'D2'}]); self.assertTrue(self.task['diagnosis_required'])
    def test_absent_usage_not_inferred_from_elapsed(self):
        self.task['first_submitted_at']=20; self.task['last_submitted_at']=35
        self.task['evidence']=[{'time':20,'unrun':[]},{'time':35,'unrun':[]}]
        passport=r.result_passport(self.task)
        self.assertIsNone(passport['observed_model_usage'])
        self.assertEqual(passport['timing']['first_version_elapsed_seconds'],10)
        self.assertEqual(passport['timing']['rework_elapsed_seconds'],15)
    def test_stale_attempt_rejected_and_explicit_user_preserved(self):
        evidence=self.evidence(); evidence['attempt']=0
        with self.assertRaises(r.OrchestrationError): r.require_readiness(self.task,evidence,'reviewer',{'fingerprint':'abc'})
        self.task['approval_mode']='explicit-user'
        with self.assertRaises(r.OrchestrationError): r.selection_source(self.task,{'origin':'observed','decision':'accepted'})

    def test_missing_timing_and_launch_do_not_fabricate_observations(self):
        self.task['first_submitted_at']=20
        timing=r.task_timing(self.task)
        self.assertEqual(timing['first_version_elapsed_seconds'],10)
        self.assertIsNone(timing['rework_elapsed_seconds'])
        self.task['last_submitted_at']=15
        self.assertIsNone(r.task_timing(self.task)['rework_elapsed_seconds'])
        passport=r.result_passport(self.task)
        self.assertEqual(passport['launch']['status'],'unavailable')
        self.assertNotEqual(passport['launch'],self.contract['checks'])
        self.contract['launch']={'status':'available','instructions':['python tool.py serve --port 8000']}
        r.readiness_contract(self.contract)
        self.assertEqual(r.result_passport(self.task)['launch']['instructions'],['python tool.py serve --port 8000'])
    def test_extra_failed_check_is_rejected(self):
        evidence=self.evidence(); evidence['checks']['extra']={'result':'fail','reason':'Broken path'}
        with self.assertRaisesRegex(r.OrchestrationError,'exactly'): r.require_readiness(self.task,evidence,'reviewer',{'fingerprint':'abc'})


class ReadinessCLITests(unittest.TestCase):
    from test_visual_workflow import VisualWorkflowTests as Fixture
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    cli=Fixture.cli
    task=Fixture.task
    record=Fixture.record

    def test_cli_defects_repeat_diagnosis_and_resolution(self):
        from test_visual_workflow import CONTEXT, PASS
        self.cli('add','A','--goal','local','--scope','*','--risk','low','--acceptance','works','--actor','director','--review-mode','manual-control')
        self.cli('assign','A','--owner','worker','--actor','director')
        self.cli('start','A','--actor','worker')
        defect={'id':'D1','criterion':'main','priority':'P1','reproduction':'fails','cause':'unknown','owner':'worker','status':'open'}
        file=self.base/'defects.json'
        for round in range(2):
            self.cli('submit','A','--actor','worker')
            if round == 1:
                self.cli('review','A','--reviewer','director','--result','pass','--findings','claim','--check',PASS,*CONTEXT,ok=False)
                self.cli('review','A','--reviewer','reviewer','--result','pass','--findings','claim','--check',PASS,'--unrun','audio unavailable',*CONTEXT,ok=False)
                self.cli('review','A','--reviewer','reviewer','--result','pass','--findings','claim','--check',PASS,*CONTEXT,ok=False)
            file.write_text(__import__('json').dumps([defect]))
            self.cli('review','A','--reviewer','reviewer','--result','fail','--findings','observed failure','--defects',str(file),*CONTEXT)
        self.assertEqual(self.task()['state'],'blocked')
        self.cli('replan','A','--actor','director','--director','director','--reason','retry',ok=False)
        self.cli('replan','A','--actor','director','--director','director','--reason','diagnosed','--diagnosis','wrong branch','--changed-approach','inspect branch before fix')
        self.assertFalse(self.task()['diagnosis_required'])
        task=self.task(); r.record_defects(task,[{**defect,'status':'fixed'}])
        self.assertEqual(r.current_defects(task)[0]['status'],'fixed')

    def test_cli_passport_separates_stale_readiness_after_inconclusive_replan(self):
        from test_visual_workflow import CONTEXT, PASS
        contract={'functional':['Works'],'user':['Goal met'],'target':'local CLI','checks':['python tool.py --help']}
        for key in ('visual','audio','performance','device'): contract[key]={'relevant':False,'reason':'Not in scope'}
        contract_file=self.base/'contract.json'; contract_file.write_text(json.dumps(contract))
        self.cli('add','A','--goal','local','--scope','*','--risk','low','--acceptance','works','--actor','director','--review-mode','manual-control','--readiness',str(contract_file))
        self.cli('assign','A','--owner','worker','--actor','director'); self.cli('start','A','--actor','worker'); self.cli('submit','A','--actor','worker')
        snap=json.loads(self.cli('snapshot','--json').stdout)['fingerprint']
        checks={key:{'result':'not_applicable','reason':'Not in scope'} for key in ('visual','audio','performance','device')}
        checks.update({key:{'result':'pass','tool':'fixture','source':'synthetic','observation':'Observed fixture'} for key in ('functional','user')})
        evidence={'reviewer':'reviewer','snapshot':snap,'contract_revision':1,'attempt':1,'checks':checks}
        file=self.base/'readiness.json'; file.write_text(json.dumps({**evidence,'checks':{**checks,'extra':{'result':'fail','reason':'Failure'}}}))
        self.cli('review','A','--reviewer','reviewer','--result','pass','--findings','fixture','--check',PASS,'--readiness-evidence',str(file),*CONTEXT,ok=False)
        file.write_text(json.dumps(evidence))
        self.cli('review','A','--reviewer','reviewer','--result','pass','--findings','fixture','--check',PASS,'--readiness-evidence',str(file),*CONTEXT)
        passport=json.loads(self.cli('passport','A').stdout)
        self.assertTrue(passport['evidence_freshness']['readiness_current'])
        self.assertIsNotNone(passport['independent_evidence']['readiness'])
        self.assertEqual(passport['launch']['status'],'unavailable')
        original=(self.root/'report.txt').read_bytes(); (self.root/'report.txt').write_text('Changed source snapshot')
        drifted=json.loads(self.cli('passport','A').stdout)
        self.assertFalse(drifted['evidence_freshness']['current_acceptance'])
        self.assertIsNone(drifted['independent_evidence']['readiness'])
        (self.root/'report.txt').write_bytes(original)
        self.cli('review','A','--reviewer','reviewer','--result','inconclusive','--findings','Coverage missing',*CONTEXT)
        passport=json.loads(self.cli('passport','A').stdout)
        self.assertIsNone(passport['independent_evidence']['readiness'])
        self.assertTrue(passport['not_verified'])
        self.cli('replan','A','--actor','director','--director','director','--reason','Clarified criteria','--acceptance','works with edge case')
        passport=json.loads(self.cli('passport','A').stdout)
        self.assertEqual(passport['contract_revision'],2)
        self.assertIsNone(passport['independent_evidence']['readiness'])
        self.assertEqual(passport['historical_evidence']['readiness']['contract_revision'],1)
        self.assertFalse(passport['evidence_freshness']['current_acceptance'])
        self.assertTrue(passport['not_verified'])

    def test_cli_observed_mode_full_lifecycle(self):
        from test_visual_workflow import VisualWorkflowTests, PASS
        for name in ('add','directions','direction_approval','preview','prototype','production','qa','general_review'):
            setattr(self,name,getattr(VisualWorkflowTests,name).__get__(self))
        self.approval={'origin':'observed','observer_origin':'independent-reviewer','decision':'accepted','reviewer':'reviewer','tool':'fixture','source':'synthetic','observation':'Synthetic observation, not real pixels'}
        self.production('ux-ui')
        self.assertEqual(self.task()['approval_mode'],'observed')
        self.record('visual-qa',self.qa(),actor='reviewer')
        self.general_review(); self.cli('integrate','A','--actor','director','--check',PASS); self.cli('complete','A','--actor','director','--check',PASS)
        self.assertEqual(self.task()['state'],'completed')
