from pathlib import Path
import ast
import copy
import argus_market_ledger as ledger
import argus_jpx_credit_valuation as valuation
import jp_market_engine as engine
from test_argus_credit_valuation_ledger import row


def test_current_consumer_can_receive_audited_loss_without_changing_d01_condition():
    source = row()
    state, _ = ledger.append_observation(ledger.empty_state(), source, now_iso=source['observedAt'])
    before = copy.deepcopy(state)
    balance = [
        {'seriesId':'credit.short_balance', 'periodEnd':'2026-09-25', 'availableFrom':'2026-10-05T15:00:00Z', 'value':1.04e12},
        {'seriesId':'credit.long_balance', 'periodEnd':'2026-09-25', 'availableFrom':'2026-10-05T15:00:00Z', 'value':6.4e12}]
    combined = valuation.extend_audited_credit_inputs(balance, ledger.latest_by_series(state, source['observedAt']))
    old = engine.evaluate_d01(balance, cutoff=source['observedAt'])
    new = engine.evaluate_d01(combined, cutoff=source['observedAt'])
    assert new['features']['valuationLossPct'] == source['value']
    assert new['conditionMet'] == old['conditionMet'] is False
    assert new['threshold'] == old['threshold']
    assert new['validationStatus'] == 'UNVALIDATED'
    assert new['pointInTimeProof']['futureRowsAdmitted'] is False
    assert state == before
    combined[-1]['metadata']['valuationCalculation']['inputs']['matchedThousandShares']=0
    assert state == before


def test_old_manual_values_or_incomplete_audit_do_not_enter_the_new_route():
    old = {**row(), 'sourceKind':'licensed'}
    damaged = row(); damaged['metadata']['valuationCalculation']['inputs']['matchedThousandShares']=0
    assert valuation.extend_audited_credit_inputs([], {'credit.valuation_loss_pct':[old,damaged]}) == []


def test_actual_scanner_consumer_preserves_balances_and_routes_audited_input():
    module = ast.parse(Path('scanner.py').read_text())
    node = next(n for n in module.body if isinstance(n, ast.FunctionDef) and n.name=='_jpx_credit_rows_effective')
    source = row()
    state, _ = ledger.append_observation(ledger.empty_state(), source, now_iso=source['observedAt'])
    base = [{'seriesId':'credit.short_balance', 'periodEnd':'2026-07-10', 'value':7e11,
             'availableFrom':'2026-07-14T07:00:00Z'}]
    namespace = {'_jpx_credit_rows':lambda:list(base), 'argus_market_ledger':ledger,
                 '_MARKET_LEDGER':state, '_ai_now_iso':lambda:source['observedAt']}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'scanner.py','exec'),namespace)
    out = namespace['_jpx_credit_rows_effective']()
    assert out[0] == base[0] and len(out) == 2
    result = engine.evaluate_d01(out,cutoff=source['observedAt'])
    assert result['features']['valuationLossPct'] == source['value']
    assert result['features']['valuationLossMethod'] == valuation.METHOD_VERSION
    assert result['conditionMet'] is True and result['validationStatus']=='UNVALIDATED'
    assert 'JPXの入力から計算' in engine.fact_note_ja('D01',result)
    namespace['_ai_now_iso'] = lambda:'2026-10-05T14:59:59Z'
    assert namespace['_jpx_credit_rows_effective']() == base
