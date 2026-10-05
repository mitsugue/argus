from copy import deepcopy
import pytest
from jp_market_engine import _sha256,CANONICAL_JP_MARKET_ENGINE_RFC_SHA256
from argus_warning_conditions import project_warning_conditions,RULE_VERSION
AT='2026-10-06T00:00:00Z'
def evidence(**changes):
    rows={'D01':{'status':'AVAILABLE','features':{'shortBalance':800_000_000_000,'shortBalanceKnownAt':AT}},
          'D02':{'status':'AVAILABLE','knownAt':AT,'marginRatio':1,'ratioBasis':'STANDARDIZED_MARGIN'},
          'D03':{'status':'AVAILABLE','conditionMet':True},
          'D04':{'status':'AVAILABLE','per':25,'conditionMet':True},
          'D05':{'status':'AVAILABLE','availableFrom':AT,'flowValue':-1,'conditionMet':False},
          'D06':{'status':'AVAILABLE','knownAt':AT,'conditionMet':False,'argusBaseline':{'warningHistogram':.01,'sampleCount':60,'uniqueSessionCount':60,'parameters':{'fast':12,'slow':26,'signal':9}},'pointInTimeProof':{'includedCount':60}},
          'D07':{'status':'AVAILABLE','conditionMet':True}}
    rows.update(changes)
    body={'informationCutoff':AT,'canonicalRfcSha256':CANONICAL_JP_MARKET_ENGINE_RFC_SHA256,'families':rows}
    return {**body,'artifactId':'jp-market-engine-evidence-'+_sha256(body)}
def test_new_direction_old_support_and_undefined_remain_separate_without_mutation():
    e=evidence();old=deepcopy(e);p=project_warning_conditions(e,cutoff=AT)
    assert p['activeCount']==3 and p['measurableCount']==4
    assert [r['state'] for r in p['signals']]==['CLEAR','ACTIVE','DATA_GATED','DATA_GATED','ACTIVE','ACTIVE','DATA_GATED']
    assert e==old and p['schemaVersion']==RULE_VERSION
    assert p['signals'][5]['knowledgeTime'] == AT
    assert all(r['performance']['status']=='UNVALIDATED' for r in p['signals'])
    assert all(not r['performanceReusedForWarning'] for r in p['legacySupportEvidence'])
    assert not p['actionAuthority'] and not p['countPredictsCrash'] and p['automaticAiCalls']==0
@pytest.mark.parametrize('field,value,active',[('D01',799_999_999_999,True),('D01',800_000_000_000,False),('D01',800_000_000_001,False),('D02',.999,False),('D02',1,True),('D05',-1,True),('D05',0,False),('D05',1,False)])
def test_boundaries(field,value,active):
    row=evidence()['families'][field]
    if field=='D01':row['features']['shortBalance']=value
    elif field=='D02':row['marginRatio']=value
    else:row['flowValue']=value
    p=project_warning_conditions(evidence(**{field:row}),cutoff=AT)
    found=next(r for r in p['signals'] if r['family']==field)
    assert found['conditionMet'] is active
@pytest.mark.parametrize('state',['STALE','MISSING','LICENSE_BLOCKED','PARTIAL','NOT_APPLICABLE'])
def test_unavailable_inputs_never_turn_into_a_counted_warning(state):
    p=project_warning_conditions(evidence(D05={'status':state,'flowValue':-999,'conditionMet':True}),cutoff=AT)
    r=p['signals'][4];assert r['state']!='ACTIVE' and r['distance'] is None
def test_unknown_margin_basis_zero_vix_and_short_history_are_not_guessed():
    p=project_warning_conditions(evidence(D02={'status':'AVAILABLE','marginRatio':2}),cutoff=AT)
    assert p['signals'][1]['state']=='DATA_GATED'
    source=evidence()['families']['D06'];source['argusBaseline']['warningHistogram']=0
    assert project_warning_conditions(evidence(D06=source),cutoff=AT)['signals'][5]['conditionMet'] is False
    source['argusBaseline']['sampleCount']=34
    assert project_warning_conditions(evidence(D06=source),cutoff=AT)['signals'][5]['state']=='DATA_GATED'
def test_tampered_or_wrong_cutoff_artifact_cannot_light_conditions():
    e=evidence();e['families']['D05']['flowValue']=-5
    p=project_warning_conditions(e,cutoff=AT);assert p['activeCount']==0 and p['rejectedEvidence']
    p=project_warning_conditions(evidence(),cutoff='2026-10-06T00:00:01Z');assert p['activeCount']==0

@pytest.mark.parametrize("known", [None, "2026-10-06", "2026-10-06T00:00:01Z"])
def test_missing_ambiguous_or_future_knowledge_never_counts(known):
    row=evidence()["families"]["D05"];row["availableFrom"]=known
    p=project_warning_conditions(evidence(D05=row),cutoff=AT)
    assert p["signals"][4]["state"]=="DATA_GATED"
    assert p["signals"][4]["distance"] is None

def test_actual_macd_sample_count_excludes_bad_closes_and_legacy_projection_is_unchanged():
    from datetime import datetime, timedelta, timezone
    import jp_market_engine as engine
    start=datetime(2026,7,1,tzinfo=timezone.utc)
    rows=[{"instrumentId":"VIX", "seriesId":"vix.close", "periodEnd":(start+timedelta(days=n)).date().isoformat(),
           "availableFrom":(start+timedelta(days=n,hours=22)).isoformat(), "close":10+n*.1} for n in range(40)]
    rows.append({**rows[-1], "periodEnd":"2026-09-30", "close":0, "availableFrom":"2026-09-30T22:00:00Z"})
    d6=engine.evaluate_d06(rows,cutoff=AT)
    assert d6["argusBaseline"]["sampleCount"]==40
    assert d6["argusBaseline"]["uniqueSessionCount"]==40
    assert d6["pointInTimeProof"]["includedCount"]==41
    e=evidence(D06=d6)
    before=deepcopy(e)
    projection=engine.project_today_sda_safe(cutoff=AT,evidence=e)
    assert projection["warningSignals"]["signals"][5]["state"] in ("ACTIVE","CLEAR")
    assert projection["marketSignals"]["signals"][5]["conditionMet"]==d6["conditionMet"]
    assert e==before and not projection["actionAuthority"]
    assert engine._content_id_valid(projection,"jp-market-engine-consumer-projection-")

@pytest.mark.parametrize("value,met",[(-.00000000001,False),(0,False),(.00000000001,True)])
def test_warning_macd_sign_uses_unrounded_value_not_legacy_display(value,met):
    row=evidence()["families"]["D06"];row["argusBaseline"].update(warningHistogram=value,histogram=0)
    found=project_warning_conditions(evidence(D06=row),cutoff=AT)["signals"][5]
    assert found["conditionMet"] is met
    assert found["distance"]["signedFromBoundary"]==value

def test_duplicate_macd_sessions_and_unbounded_numeric_values_are_not_admitted():
    row=evidence()["families"]["D06"];row["argusBaseline"]["uniqueSessionCount"]=59
    assert project_warning_conditions(evidence(D06=row),cutoff=AT)["signals"][5]["state"]=="DATA_GATED"
    for value in (True,10**400):
        row=evidence()["families"]["D05"];row["flowValue"]=value
        assert project_warning_conditions(evidence(D05=row),cutoff=AT)["signals"][4]["state"]=="DATA_GATED"
