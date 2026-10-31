"""追加観測の影響が届く前の履歴は、全再生と完全一致する範囲だけ再利用。"""
from copy import deepcopy
from unittest.mock import Mock
import pytest
import jp_market_features as new
from test_jp_market_feature_history_stability import inputs, cutoffs, day, vix

NOW=str(day(60))+'T12:00:00Z';ATS=cutoffs(60,NOW)

def saved(data):return {**new.build_feature_history(cutoffs=ATS,**data),'status':'AVAILABLE'}

def semantic(value):return {k:v for k,v in value.items()if k not in ('calculationWork','reuseDecision')}

def test_late_appended_observation_replays_only_affected_tail_with_exact_full_output(monkeypatch):
 before=inputs(NOW,n=60,vix_rows=vix(57));after=inputs(NOW,n=60,vix_rows=vix(58));prior=saved(before);baseline=new.build_feature_history(cutoffs=ATS,**after)
 wrapped=Mock(wraps=new.build_market_features);monkeypatch.setattr(new,'build_market_features',wrapped)
 actual=new.build_feature_history(cutoffs=ATS,previous_history=prior,**after)
 assert semantic(actual)==semantic(baseline)
 assert actual['calculationWork']=={'reusedCutoffs':58,'evaluatedCutoffs':3}
 assert wrapped.call_count==3 and actual['reuseDecision']['reason']=='appended_rows_replay_tail'
 assert prior['status']=='AVAILABLE' and before['price_series']['vix']==vix(57)

@pytest.mark.parametrize('change',['historical_value','historical_receipt','unbounded_append','known_early_append'])
def test_changes_that_could_reach_old_cutoffs_cannot_hide_in_a_reused_tail(change):
 before=inputs(NOW,n=60,vix_rows=vix(57));after=deepcopy(before);rows=after['price_series']['vix']
 if change=='historical_value':rows[5]['value']+=3;rows[5]['close']+=3
 elif change=='historical_receipt':rows[5]['availableFrom']=str(day(9))+'T00:00:00Z'
 elif change=='unbounded_append':rows.append({k:v for k,v in rows[-1].items()if k!='availableFrom'})
 else:rows.append({**rows[1],'date':str(day(0)),'availableFrom':str(day(0))+'T00:00:00Z','sourceRef':'fixture:another','revision':1,'knownAt':str(day(0))+'T00:00:00Z'})
 baseline=new.build_feature_history(cutoffs=ATS,**after)
 actual=new.build_feature_history(cutoffs=ATS,previous_history=saved(before),**after)
 assert semantic(actual)==semantic(baseline)
 assert actual['calculationWork']['reusedCutoffs']==0


def test_new_correction_is_not_applied_before_its_actual_knowledge_time():
 before=inputs(NOW,n=60,vix_rows=vix(57));after=deepcopy(before);r=after['price_series']['vix'][5]
 after['price_series']['vix'].append({**r,'value':40,'close':40,'revision':1,'knownAt':str(day(58))+'T00:00:00Z'})
 baseline=new.build_feature_history(cutoffs=ATS,**after)
 actual=new.build_feature_history(cutoffs=ATS,previous_history=saved(before),**after)
 assert semantic(actual)==semantic(baseline)
 assert actual['calculationWork']['reusedCutoffs']==0
 assert actual['reuseDecision']=={'reason':'append_can_affect_prior_cutoff','source':'price_series:vix'}


def test_future_append_refreshes_endpoint_audit_without_replaying_earlier_features():
 before=inputs(NOW,n=60,vix_rows=vix(57));after=deepcopy(before);after['price_series']['vix'].append({**vix(58)[-1],'availableFrom':str(day(70))+'T00:00:00Z'})
 baseline=new.build_feature_history(cutoffs=ATS,**after)
 actual=new.build_feature_history(cutoffs=ATS,previous_history=saved(before),**after)
 assert semantic(actual)==semantic(baseline)
 assert actual['calculationWork']['reusedCutoffs']==len(ATS)


def test_multiple_append_sources_use_earliest_possible_effect():
 before=inputs(NOW,n=60,vix_rows=vix(57));before['price_series']['nikkei']=before['price_series']['nikkei'][:55]
 after=inputs(NOW,n=60,vix_rows=vix(58));baseline=new.build_feature_history(cutoffs=ATS,**after)
 actual=new.build_feature_history(cutoffs=ATS,previous_history=saved(before),**after)
 assert semantic(actual)==semantic(baseline)
 assert actual['calculationWork']['reusedCutoffs']==55


def test_observation_known_exactly_at_cutoff_is_recomputed_at_that_cutoff():
 before=inputs(NOW,n=60,vix_rows=vix(57));after=inputs(NOW,n=60,vix_rows=vix(58))
 after['price_series']['vix'][-1]['availableFrom']=str(day(58))+'T23:59:59Z'
 baseline=new.build_feature_history(cutoffs=ATS,**after)
 actual=new.build_feature_history(cutoffs=ATS,previous_history=saved(before),**after)
 assert semantic(actual)==semantic(baseline)
 assert actual['calculationWork']['reusedCutoffs']==58
