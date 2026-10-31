from pathlib import Path
import sys,types,threading,inspect
import scanner
from unittest.mock import patch
import pytest

ROOT=Path(__file__).resolve().parent

class Clock:
    def __init__(self,unsupported=False):self.wall=100.;self.cpu=0.;self.unsupported=unsupported
    def monotonic(self):return self.wall
    def time(self):return 2000.
    def thread_time(self):
        if self.unsupported:raise NotImplementedError('not-supported')
        return self.cpu
    def advance(self,wall,cpu):self.wall+=wall;self.cpu+=cpu

def run(*, fail=False, unsupported=False):
    clock=Clock(unsupported);calls=[];module=types.ModuleType('argus_earnings_history')
    def read(*args,**kwargs):calls.append(('read',args,kwargs));clock.advance(2,.5);return ['financial']
    def coverage(*args,**kwargs):
        calls.append(('coverage',args,kwargs));clock.advance(3,.75)
        if fail:raise ValueError('private-test-value')
        return {'date':'coverage'}
    def company(*args,**kwargs):calls.append(('company',args,kwargs));clock.advance(4,1.);return {'code':'company'}
    module.read=read;module.read_coverage=coverage;module.read_company_coverage=company
    def instrument(stage,callback):
        clock.advance(5,.25)
        try:return callback()
        finally:clock.advance(7,.25)
    ns={'time':clock,'_decision_evidence_stage':instrument,'_ai_now_iso':lambda:'2026-10-31T01:00:00Z',
        '_JP_FINANCIAL_VERIFY_LOCK':threading.Lock(),'_JP_FINANCIAL_VERIFY':{'state':'RUNNING'},
        '_JP_FINANCIAL_INPUTS':{'key':None,'data':None,'failedKey':None,'failedAt':0}}
    exec(compile(inspect.getsource(scanner._jp_financial_verify_worker), 'financial_worker_contract', 'exec'),ns)
    with patch.dict(sys.modules,{'argus_earnings_history':module}):
        ns['_jp_financial_verify_worker']('isolated.sqlite3',['1234'],'2026-10-31T00:00:00Z','same-key')
    return ns['_JP_FINANCIAL_VERIFY'],ns['_JP_FINANCIAL_INPUTS'],calls

def test_callback_time_is_separate_from_existing_observer_and_cpu_wait():
    after,data,calls=run()
    expected = [
        ('read', ('isolated.sqlite3',), {'cutoff':'2026-10-31T00:00:00Z','member_codes':['1234']}),
        ('coverage', ('isolated.sqlite3',), {'cutoff':'2026-10-31T00:00:00Z'}),
        ('company', ('isolated.sqlite3',), {'cutoff':'2026-10-31T00:00:00Z','member_codes':['1234']}),
    ]
    assert calls == expected
    assert data['data'] == (['financial'], {'date':'coverage'}, {'code':'company'})
    assert data['key']=='same-key' and data['failedKey'] is None
    assert after['state']=='DONE' and after['seconds']==45
    assert after['phaseSeconds']=={'financial_read':2.,'financial_coverage':3.,'company_coverage':4.}
    assert after['phaseCpuSeconds']=={'financial_read':.5,'financial_coverage':.75,'company_coverage':1.}
    assert after['cpuSeconds']==3.75
    assert sum(after['phaseSeconds'].values())<after['seconds']


def test_failure_keeps_failed_verdict_and_only_attempted_phase_metrics():
    after,data,calls=run(fail=True)
    assert [c[0] for c in calls] == ['read','coverage']
    assert data['data'] is None and data['failedKey']=='same-key'
    assert after['state']=='FAILED' and after['errorClass']=='ValueError'
    assert set(after['phaseSeconds'])=={'financial_read','financial_coverage'}
    assert 'private-test-value' not in str(after)


def test_missing_thread_cpu_clock_does_not_fail_or_become_zero():
    after,data,calls=run(unsupported=True)
    assert len(calls)==3 and data['key']=='same-key' and after['state']=='DONE'
    assert after['cpuSeconds'] is None and all(v is None for v in after['phaseCpuSeconds'].values())
