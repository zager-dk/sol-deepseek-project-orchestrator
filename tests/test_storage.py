"""Isolated selection and exact-namespace storage contract checks."""
import json
import subprocess
import sys
import tempfile
import unittest
import os
import sys as _sys
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from unittest import mock
from pathlib import Path
from test_support import cleanup_temporary_directory

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'orchestrate.py'

class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'repo'; self.root.mkdir()
        self.home=Path(self.tmp.name)/'home'; self.home.mkdir(); self.gitconfig=Path(self.tmp.name)/'gitconfig'; self.gitconfig.write_text('[user]\n name=T\n email=t@invalid\n')
        self.env=os.environ.copy(); self.env.update({'HOME':str(self.home),'USERPROFILE':str(self.home),'GIT_CONFIG_GLOBAL':str(self.gitconfig),'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0','GIT_CEILING_DIRECTORIES':str(Path(self.tmp.name)),'PYTHONDONTWRITEBYTECODE':'1'})
        subprocess.run(['git','init','-q'],cwd=self.root,env=self.env,check=True)
        (self.root/'src').mkdir(); (self.root/'src'/'ORCHESTRATOR.foo.tmp').write_text('visible')
        subprocess.run(['git','add','.'],cwd=self.root,env=self.env,check=True)
        subprocess.run(['git','commit','-qm','base'],cwd=self.root,env=self.env,check=True)
    def tearDown(self): cleanup_temporary_directory(self.tmp)
    def run_cli(self,*args,ok=True):
        p=subprocess.run([sys.executable,str(SCRIPT),'--project',str(self.root),*args],cwd=self.root,env=self.env,capture_output=True,text=True)
        if ok and p.returncode: self.fail(p.stderr)
        if not ok and p.returncode==0: self.fail(f'expected refusal: {args}')
        return p
    def load_runtime(self,name):
        spec=importlib.util.spec_from_file_location(name,SCRIPT)
        runtime=importlib.util.module_from_spec(spec); _sys.modules[spec.name]=runtime; spec.loader.exec_module(runtime)
        runtime.ACTIVE_DATA_DIR=self.root/'ledger'
        return runtime
    def test_legacy_default_and_explicit_binding_selection(self):
        self.run_cli('init'); self.assertTrue((self.root/'.codex'/'ORCHESTRATOR.json').exists())
        self.run_cli('bind-storage','--data-dir','ledger',ok=False)
        (self.root/'.codex'/'ORCHESTRATOR.json').unlink()
        self.run_cli('bind-storage','--data-dir','ledger')
        self.run_cli('--data-dir','ledger','init')
        self.assertTrue((self.root/'ledger'/'ORCHESTRATOR.json').exists())
        snapshot=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertIn('.codex/ORCHESTRATOR_STORAGE.json',snapshot['paths'])
        self.run_cli('--data-dir','elsewhere','snapshot','--json',ok=False)
        self.assertTrue((self.root/'src'/'ORCHESTRATOR.foo.tmp').exists())
    def test_absolute_contained_directory_is_accepted_and_metadata_rejected(self):
        absolute=self.root/'absolute-ledger'
        self.run_cli('bind-storage','--data-dir',str(absolute))
        self.run_cli('--data-dir',str(absolute),'init')
        self.assertTrue((absolute/'ORCHESTRATOR.json').is_file())
        self.run_cli('bind-storage','--data-dir','.git/nested',ok=False)
        self.run_cli('bind-storage','--data-dir','.CODEX/private',ok=False)
        other=Path(self.tmp.name)/'other-repo'; other.mkdir(); subprocess.run(['git','init','-q'],cwd=other,env=self.env,check=True)
        occupied=other/'ledger'; occupied.mkdir(); (occupied/'ORCHESTRATOR.json').write_text('{}')
        proc=subprocess.run([sys.executable,str(SCRIPT),'--project',str(other),'bind-storage','--data-dir','ledger'],cwd=other,env=self.env,capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertFalse((other/'.codex'/'ORCHESTRATOR_STORAGE.json').exists())
    def test_no_migration_escape_or_selector_tamper_fallback(self):
        self.run_cli('init'); self.run_cli('bind-storage','--data-dir','ledger',ok=False)
        (self.root/'.codex'/'ORCHESTRATOR.json').unlink()
        self.run_cli('bind-storage','--data-dir','../outside',ok=False)
        self.run_cli('bind-storage','--data-dir','ledger')
        (self.root/'.codex'/'ORCHESTRATOR_STORAGE.json').write_text('{broken')
        self.run_cli('snapshot','--json',ok=False)
        self.assertTrue((self.root/'ledger'/'ORCHESTRATOR.json').exists() is False)
    def test_lookalike_files_remain_in_snapshot(self):
        self.run_cli('init')
        (self.root/'src'/'ORCHESTRATOR.foo.tmp').write_text('changed')
        (self.root/'src'/'ORCHESTRATOR.abcd.tmp').write_text('visible too')
        paths=json.loads(self.run_cli('snapshot','--json').stdout)['paths']
        self.assertIn('src/ORCHESTRATOR.foo.tmp',paths)
        self.assertIn('src/ORCHESTRATOR.abcd.tmp',paths)
    def test_bound_snapshot_tracks_selector_source_index_and_head_only(self):
        self.run_cli('bind-storage','--data-dir','ledger'); self.run_cli('init')
        ledger=self.root/'ledger'
        for name in ('ORCHESTRATOR.json','ORCHESTRATOR.lock','ORCHESTRATOR.tmp'):
            if name!='ORCHESTRATOR.json': (ledger/name).write_text('reserved')
        before=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertIn('.codex/ORCHESTRATOR_STORAGE.json',before['paths'])
        self.assertFalse(any(path.startswith('ledger/') for path in before['paths']))
        selector=self.root/'.codex'/'ORCHESTRATOR_STORAGE.json'
        selector.write_bytes(selector.read_bytes()+b' ')
        selector_drift=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotEqual(before['dirty_digest'],selector_drift['dirty_digest'])
        self.assertIn('.codex/ORCHESTRATOR_STORAGE.json',selector_drift['paths'])
        (self.root/'src'/'tracked.txt').write_text('dirty source')
        source=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotEqual(selector_drift['dirty_digest'],source['dirty_digest'])
        subprocess.run(['git','add','src/tracked.txt'],cwd=self.root,env=self.env,check=True)
        staged=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotEqual(source['index_digest'],staged['index_digest'])
        subprocess.run(['git','commit','-qm','source change'],cwd=self.root,env=self.env,check=True)
        headed=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotEqual(staged['head'],headed['head'])
    @unittest.skipUnless(os.name=='nt','Windows path identity is case-insensitive')
    def test_windows_case_alias_excludes_only_selected_ledger_bookkeeping(self):
        actual=self.root/'ledger'; actual.mkdir()
        self.run_cli('bind-storage','--data-dir','LEDGER')
        self.run_cli('init')
        self.assertTrue(actual.is_dir())
        self.assertTrue((actual/'ORCHESTRATOR.json').is_file())
        before=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotIn('ledger/ORCHESTRATOR.json',before['paths'])
        self.assertIn('.codex/ORCHESTRATOR_STORAGE.json',before['paths'])
        common=['--goal','goal','--scope','src/a.py','--acceptance','observable','--actor','director']
        self.run_cli('add','CASE',*common)
        ledger_only=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertEqual(before['fingerprint'],ledger_only['fingerprint'])
        selector=self.root/'.codex'/'ORCHESTRATOR_STORAGE.json'
        selector.write_bytes(selector.read_bytes()+b' ')
        selector_change=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotEqual(ledger_only['fingerprint'],selector_change['fingerprint'])
        self.assertIn('.codex/ORCHESTRATOR_STORAGE.json',selector_change['paths'])
        lookalike=self.root/'src'/'ORCHESTRATOR.foo.tmp'
        lookalike.write_text('visible after source change')
        source_change=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotEqual(selector_change['fingerprint'],source_change['fingerprint'])
        self.assertIn('src/ORCHESTRATOR.foo.tmp',source_change['paths'])
    @unittest.skipUnless(os.name=='posix','POSIX path identity is case-sensitive')
    def test_posix_selected_bookkeeping_preserves_distinct_case_path(self):
        (self.root/'ledger').mkdir()
        self.run_cli('bind-storage','--data-dir','ledger')
        self.run_cli('init')
        distinct=self.root/'LEDGER'; distinct.mkdir(); (distinct/'visible.txt').write_text('visible')
        snapshot=json.loads(self.run_cli('snapshot','--json').stdout)
        self.assertNotIn('ledger/ORCHESTRATOR.json',snapshot['paths'])
        self.assertIn('LEDGER/visible.txt',snapshot['paths'])
    def test_bound_lifecycle_recovery_replan_and_same_binding_idempotence(self):
        self.run_cli('bind-storage','--data-dir','ledger')
        selector=(self.root/'.codex'/'ORCHESTRATOR_STORAGE.json').read_bytes()
        self.run_cli('init','--review-round-limit','4')
        self.run_cli('bind-storage','--data-dir','ledger')
        self.assertEqual(selector,(self.root/'.codex'/'ORCHESTRATOR_STORAGE.json').read_bytes())
        common=['--goal','goal','--scope','src/a.py','--acceptance','observable','--actor','director']
        self.run_cli('--data-dir','ledger','add','T',*common)
        checks=['--scenario','observable','--fresh-context-attested','--context-item','contract','--context-item','diff','--context-item','relevant-code','--context-item','verification-results']
        self.run_cli('--data-dir','ledger','plan-review','T','--actor','director','--director','director','--reviewer','plan-1','--contract-version','1',*checks)
        self.run_cli('--data-dir','ledger','assign','T','--owner','worker-1','--actor','director')
        self.run_cli('--data-dir','ledger','start','T','--actor','worker-1')
        self.run_cli('--data-dir','ledger','submit','T','--actor','worker-1')
        review=['--reviewer','plan-1','--result','pass','--check','PASS; command=unittest; result=exit 0; evidence=first selected-storage pass','--findings','initial pass','--fresh-context-attested','--context-item','contract','--context-item','diff','--context-item','relevant-code','--context-item','verification-results']
        self.run_cli('--data-dir','ledger','review','T',*review)
        blocked=['--reviewer','plan-1','--result','inconclusive','--findings','test drift requires contract update','--fresh-context-attested','--context-item','contract','--context-item','diff','--context-item','relevant-code','--context-item','verification-results']
        self.run_cli('--data-dir','ledger','review','T',*blocked)
        previous=json.loads((self.root/'ledger'/'ORCHESTRATOR.json').read_text())['tasks']['T']['evidence'][-2]
        self.assertEqual(previous['result'],'pass')
        self.run_cli('--data-dir','ledger','replan','T','--actor','director','--director','director','--reason','contract adjustment','--acceptance','new observable')
        self.run_cli('--data-dir','ledger','plan-review','T','--actor','director','--director','director','--reviewer','plan-2','--contract-version','2',*checks)
        self.run_cli('--data-dir','ledger','assign','T','--owner','plan-2','--actor','director',ok=False)
        self.run_cli('--data-dir','ledger','assign','T','--owner','worker-2','--actor','director')
        self.run_cli('--data-dir','ledger','start','T','--actor','worker-2')
        self.run_cli('--data-dir','ledger','interrupt','T','--actor','worker-2')
        self.run_cli('--data-dir','ledger','recover','T','--owner','worker-3','--actor','director','--context','restart with current diff','--old-agent-interrupted')
        self.run_cli('--data-dir','ledger','start','T','--actor','worker-3')
        self.run_cli('--data-dir','ledger','submit','T','--actor','worker-3')
        review=['--reviewer','plan-2','--result','pass','--check','PASS; command=unittest; result=exit 0; evidence=selected-storage lifecycle verified','--findings','no defects','--fresh-context-attested','--context-item','contract','--context-item','diff','--context-item','relevant-code','--context-item','verification-results']
        self.run_cli('--data-dir','ledger','review','T',*review)
        (self.root/'src'/'a.py').write_text('changed after review')
        self.run_cli('--data-dir','ledger','integrate','T','--actor','director','--check','PASS; command=check; result=exit 0; evidence=first integration attempt',ok=False)
        self.run_cli('--data-dir','ledger','review','T',*review)
        passed=['--check','PASS; command=check; result=exit 0; evidence=selected storage integration verified']
        self.run_cli('--data-dir','ledger','integrate','T','--actor','director',*passed)
        self.run_cli('--data-dir','ledger','complete','T','--actor','director',*passed)
        db=json.loads((self.root/'ledger'/'ORCHESTRATOR.json').read_text())
        self.assertEqual(db['tasks']['T']['contract_revision'],2)
        self.assertTrue(db['tasks']['T']['acceptance_plans'][0]['invalidated'])
        self.assertEqual(db['tasks']['T']['owner'],'worker-3')
        self.assertEqual(db['tasks']['T']['state'],'completed')
    def test_config_parent_link_refused_before_selector_access(self):
        outside=Path(self.tmp.name)/'external-config'; outside.mkdir()
        try: (self.root/'.codex').symlink_to(outside,target_is_directory=True)
        except (OSError,NotImplementedError): self.skipTest('directory symlink unavailable')
        self.run_cli('snapshot','--json',ok=False)
    def test_atomic_replace_failure_preserves_existing_ledger(self):
        self.run_cli('bind-storage','--data-dir','ledger'); self.run_cli('init')
        spec=importlib.util.spec_from_file_location('candidate_storage_runtime',SCRIPT)
        runtime=importlib.util.module_from_spec(spec); _sys.modules[spec.name]=runtime; spec.loader.exec_module(runtime)
        runtime.ACTIVE_DATA_DIR=self.root/'ledger'
        path=self.root/'ledger'/'ORCHESTRATOR.json'; before=path.read_bytes()
        with mock.patch.object(runtime.os,'replace',side_effect=OSError('injected replace failure')):
            with self.assertRaises(OSError): runtime.save(self.root,runtime.empty_db())
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'ledger'/'ORCHESTRATOR.tmp').exists())
        with mock.patch.object(runtime.os,'fsync',side_effect=OSError('injected fsync failure')):
            with self.assertRaises(OSError): runtime.save(self.root,runtime.empty_db())
        self.assertEqual(path.read_bytes(),before)
        self.assertFalse((self.root/'ledger'/'ORCHESTRATOR.tmp').exists())
        temp=self.root/'ledger'/'ORCHESTRATOR.tmp'; temp.write_text('stale')
        with self.assertRaises(runtime.OrchestrationError): runtime.save(self.root,runtime.empty_db())
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(temp.read_text(),'stale')
    def test_save_refuses_prepublication_foreign_temp_substitution(self):
        self.run_cli('bind-storage','--data-dir','ledger'); self.run_cli('init')
        self.run_cli('add','T','--goal','goal','--scope','src/a.py','--acceptance','observable','--actor','director')
        runtime=self.load_runtime('candidate_prepublication_temp_runtime')
        ledger=self.root/'ledger'/'ORCHESTRATOR.json'; before=ledger.read_bytes(); before_db=json.loads(before)
        temp=self.root/'ledger'/'ORCHESTRATOR.tmp'; moved=self.root/'owned-temp-moved-aside'; foreign=b'foreign temporary replacement\n'
        original_verify=runtime.verify_selection
        def substitute_after_write(root):
            os.replace(temp,moved)
            temp.write_bytes(foreign)
            original_verify(root)
        with mock.patch.object(runtime,'verify_selection',side_effect=substitute_after_write):
            with self.assertRaises(runtime.OrchestrationError): runtime.save(self.root,runtime.empty_db())
        self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual(json.loads(ledger.read_bytes())['history'],before_db['history'])
        self.assertTrue(moved.is_file())
        self.assertEqual(temp.read_bytes(),foreign)
        moved.unlink(); temp.unlink()
    def test_replace_failure_does_not_delete_foreign_temp_replacement(self):
        self.run_cli('bind-storage','--data-dir','ledger'); self.run_cli('init')
        self.run_cli('add','T','--goal','goal','--scope','src/a.py','--acceptance','observable','--actor','director')
        runtime=self.load_runtime('candidate_replace_temp_runtime')
        ledger=self.root/'ledger'/'ORCHESTRATOR.json'; before=ledger.read_bytes(); before_db=json.loads(before)
        temp=self.root/'ledger'/'ORCHESTRATOR.tmp'; moved=self.root/'owned-temp-moved-aside'; foreign=b'foreign file at replaced temp path\n'
        real_replace=runtime.os.replace
        def replace_then_fail(source,destination):
            self.assertEqual(Path(source),temp)
            self.assertEqual(Path(destination),ledger)
            real_replace(source,moved)
            temp.write_bytes(foreign)
            raise OSError('injected replace failure after foreign substitution')
        with mock.patch.object(runtime.os,'replace',side_effect=replace_then_fail):
            with self.assertRaisesRegex(OSError,'injected replace failure'):
                runtime.save(self.root,runtime.empty_db())
        self.assertEqual(ledger.read_bytes(),before)
        self.assertEqual(json.loads(ledger.read_bytes())['history'],before_db['history'])
        self.assertTrue(moved.is_file())
        self.assertEqual(temp.read_bytes(),foreign)
        moved.unlink(); temp.unlink()
    def test_save_write_and_fsync_failures_close_temp_descriptor_and_cleanup(self):
        self.run_cli('bind-storage','--data-dir','ledger'); self.run_cli('init')
        self.run_cli('add','T','--goal','goal','--scope','src/a.py','--acceptance','observable','--actor','director')
        runtime=self.load_runtime('candidate_save_failure_runtime')
        ledger=self.root/'ledger'/'ORCHESTRATOR.json'; before=ledger.read_bytes(); before_db=json.loads(before)
        temp=self.root/'ledger'/'ORCHESTRATOR.tmp'; lock=self.root/'ledger'/'ORCHESTRATOR.lock'
        real_open=runtime.os.open; real_fsync=runtime.os.fsync
        for failure in ('fdopen','write','fsync'):
            with self.subTest(failure=failure):
                captured=[]
                def capture_open(path,*args,**kwargs):
                    fd=real_open(path,*args,**kwargs)
                    if Path(path)==temp: captured.append(fd)
                    return fd
                def fail_temp_fsync(fd):
                    if fd in captured: raise OSError('injected temp fsync failure')
                    return real_fsync(fd)
                with mock.patch.object(runtime.os,'open',side_effect=capture_open):
                    if failure=='fdopen':
                        with mock.patch.object(runtime.os,'fdopen',side_effect=OSError('injected fdopen failure')):
                            with self.assertRaisesRegex(OSError,'injected fdopen failure'):
                                with runtime.exclusive_lock(lock): runtime.save(self.root,runtime.empty_db())
                    elif failure=='write':
                        with mock.patch.object(runtime.json,'dump',side_effect=OSError('injected temp write failure')):
                            with self.assertRaisesRegex(OSError,'injected temp write failure'):
                                with runtime.exclusive_lock(lock): runtime.save(self.root,runtime.empty_db())
                    else:
                        with mock.patch.object(runtime.os,'fsync',side_effect=fail_temp_fsync):
                            with self.assertRaisesRegex(OSError,'injected temp fsync failure'):
                                with runtime.exclusive_lock(lock): runtime.save(self.root,runtime.empty_db())
                self.assertEqual(len(captured),1)
                with self.assertRaises(OSError): os.fstat(captured[0])
                self.assertFalse(temp.exists())
                self.assertFalse(lock.exists())
                self.assertEqual(ledger.read_bytes(),before)
                self.assertEqual(json.loads(ledger.read_bytes())['history'],before_db['history'])
                with runtime.exclusive_lock(lock): pass
                self.assertFalse(lock.exists())
    def test_lock_write_and_fsync_failures_close_descriptor_remove_owned_lock_and_preserve_ledger(self):
        self.run_cli('bind-storage','--data-dir','ledger'); self.run_cli('init')
        spec=importlib.util.spec_from_file_location('candidate_lock_runtime',SCRIPT)
        runtime=importlib.util.module_from_spec(spec); _sys.modules[spec.name]=runtime; spec.loader.exec_module(runtime)
        runtime.selected_dir(self.root,None)
        lock=self.root/'ledger'/'ORCHESTRATOR.lock'; ledger=self.root/'ledger'/'ORCHESTRATOR.json'; before=ledger.read_bytes()
        for target in ('write','write-zero','fsync'):
            captured=[]
            def fail_write(fd,*_args): captured.append(fd); raise OSError('injected write failure')
            def zero_write(fd,*_args): captured.append(fd); return 0
            def fail_fsync(fd,*_args): captured.append(fd); raise OSError('injected fsync failure')
            patcher=(mock.patch.object(runtime.os,'write',side_effect=fail_write) if target=='write' else
                     mock.patch.object(runtime.os,'write',side_effect=zero_write) if target=='write-zero' else
                     mock.patch.object(runtime.os,'fsync',side_effect=fail_fsync))
            with patcher:
                with self.assertRaises(OSError):
                    with runtime.exclusive_lock(lock): pass
            self.assertEqual(len(captured),1)
            with self.assertRaises(OSError): os.fstat(captured[0])
            self.assertFalse(lock.exists())
            self.assertEqual(ledger.read_bytes(),before)
            with runtime.exclusive_lock(lock): pass
            self.assertFalse(lock.exists())
        lock.write_bytes(b'foreign lock bytes')
        foreign_before=lock.read_bytes()
        with self.assertRaises(runtime.OrchestrationError):
            with runtime.exclusive_lock(lock): pass
        self.assertEqual(lock.read_bytes(),foreign_before)
        lock.unlink()
    def test_lock_cleanup_does_not_remove_foreign_replacement(self):
        spec=importlib.util.spec_from_file_location('candidate_lock_replacement_runtime',SCRIPT)
        runtime=importlib.util.module_from_spec(spec); _sys.modules[spec.name]=runtime; spec.loader.exec_module(runtime)
        lock=self.root/'.codex'/'ORCHESTRATOR.lock'; lock.parent.mkdir()
        moved=self.root/'owned-lock-moved-aside'
        with runtime.exclusive_lock(lock):
            lock.replace(moved)
            lock.write_bytes(b'foreign replacement bytes')
        self.assertEqual(lock.read_bytes(),b'foreign replacement bytes')
        moved.unlink(); lock.unlink()
    def test_generated_hook_commands_forward_explicit_path_with_quoting(self):
        install_path=Path(__file__).resolve().parents[1]/'scripts'/'install.py'
        spec=importlib.util.spec_from_file_location('candidate_storage_installer',install_path)
        installer=importlib.util.module_from_spec(spec); _sys.modules[spec.name]=installer; spec.loader.exec_module(installer)
        config=json.loads(installer.build_hooks_config(Path('C:/hooks'),'folder with spaces').decode())
        handlers=[]
        for groups in config['hooks'].values():
            for group in groups:
                handlers.extend(group['hooks'])
        commands=[item['command'] for item in handlers]
        self.assertEqual(len(commands),2)
        self.assertTrue(all("--data-dir 'folder with spaces'" in command for command in commands))
    def test_concurrent_legacy_init_and_bind_never_create_two_registries(self):
        def call(*args):
            return subprocess.run([sys.executable,str(SCRIPT),'--project',str(self.root),*args],cwd=self.root,env=self.env,capture_output=True,text=True)
        with ThreadPoolExecutor(max_workers=2) as pool:
            init=pool.submit(call,'init'); bind=pool.submit(call,'bind-storage','--data-dir','ledger')
            init_result,bind_result=init.result(),bind.result()
        selector=self.root/'.codex'/'ORCHESTRATOR_STORAGE.json'
        legacy=self.root/'.codex'/'ORCHESTRATOR.json'
        selected=self.root/'ledger'/'ORCHESTRATOR.json'
        self.assertFalse(legacy.exists() and selected.exists())
        if selector.exists():
            self.assertEqual(bind_result.returncode,0,bind_result.stderr)
            self.assertFalse(legacy.exists())
            if selected.exists(): self.assertEqual(init_result.returncode,0,init_result.stderr)
            else:
                self.assertNotEqual(init_result.returncode,0)
                self.assertIn('ORCHESTRATOR_STORAGE.lock',init_result.stderr)
                self.run_cli('init')
                self.assertTrue(selected.exists())
        else:
            self.assertTrue(legacy.exists())
            self.assertFalse(selected.exists())
            self.assertEqual(init_result.returncode,0,init_result.stderr)
            self.assertNotEqual(bind_result.returncode,0)
    def test_held_bootstrap_lock_causes_clean_init_refusal_then_retry_succeeds(self):
        self.run_cli('bind-storage','--data-dir','ledger')
        spec=importlib.util.spec_from_file_location('candidate_bootstrap_runtime',SCRIPT)
        runtime=importlib.util.module_from_spec(spec); _sys.modules[spec.name]=runtime; spec.loader.exec_module(runtime)
        runtime.selected_dir(self.root,None)
        with runtime.exclusive_lock(self.root/runtime.BOOTSTRAP_REL):
            refused=self.run_cli('init',ok=False)
            self.assertIn('ORCHESTRATOR_STORAGE.lock',refused.stderr)
            self.assertFalse((self.root/'ledger'/'ORCHESTRATOR.json').exists())
            self.assertFalse((self.root/'.codex'/'ORCHESTRATOR.json').exists())
        self.run_cli('init')
        self.assertTrue((self.root/'ledger'/'ORCHESTRATOR.json').exists())

if __name__=='__main__': unittest.main()
