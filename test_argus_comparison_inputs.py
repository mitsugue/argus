"""Full legacy outcome parity and PIT rejection across research-batch refreshes."""
import copy
from unittest.mock import patch

import pytest

import argus_comparison_inputs as inputs
import jp_market_analogs as analogs
import jp_market_price_paths as paths
from test_argus_comparison_preparation import fixed_study
from test_jp_market_analog_cache_revisions import BARS, DAYS, CUTOFF, row


def research(**changes):
    return row('material_reaction.CPI.3', 1, eventId='synthetic:CPI', eventType='CPI',
        reactionWindowSessions=3, sourceRowsHash='a'*64, sourceSha256='b'*64,
        eventSourceSha256='e'*64, status='AVAILABLE', actionAuthority=False,
        historicalVintageVerified=False, actualPublicationTimeVerified=False,
        availabilityBasis='RESEARCH_KNOWN_AT_ENDPOINT_CLOSE',
        derivationBasis='DAILY_CLOSE_REFERENCE_NOT_INTRADAY_ATTRIBUTION',
        eventTimeBasis='ARCHIVED_RELEASE_DATE_FIXED_TIME_RULE', **changes)


def groups(rows):
    return {'states': [row('credit.loss_pct', -1)], 'conditions': [],
            'reactions': [], 'research': rows}


def compare(cache, value, *, horizon=5, prepared=True):
    source = inputs.prepare(value) if prepared else value
    return paths.cached_index_comparison(BARS, cutoff=CUTOFF, session_dates=DAYS,
        horizon_sessions=horizon, backtest_cache=cache,
        state_rows=source['states'], condition_rows=source['conditions'],
        reaction_rows=source['reactions'], research_reaction_rows=source['research'])


@pytest.mark.parametrize('horizon', [1, 5, 10, 20])
def test_full_result_and_study_key_equal_legacy_engine(horizon):
    original = groups([research()]); before = copy.deepcopy(original)
    old, new = {}, {}
    assert compare(new, original, horizon=horizon) == compare(old, original, horizon=horizon, prepared=False)
    assert new['key'] == old['key']
    assert original == before
    projected = inputs.prepare(original)
    for name in ('states', 'conditions', 'reactions'):
        assert projected[name] is original[name]
    assert projected['research'][0]['eventSourceSha256'] == 'e'*64


def test_batch_receipt_refresh_reuses_candidates_without_recomputing_study():
    cache = {}; initial = groups([research()]); first = compare(cache, initial)
    candidates = cache['sealedCandidates']; key = cache['key']
    refreshed = copy.deepcopy(initial)
    refreshed['research'][0].update(sourceRowsHash='c'*64, sourceSha256='d'*64)
    before = copy.deepcopy(refreshed)
    with patch.object(analogs, 'build_episode', wraps=analogs.build_episode) as build:
        assert compare(cache, refreshed) == first
    # One current episode only; no historical anchor is rebuilt.
    assert build.call_count == 1
    assert cache['sealedCandidates'] is candidates and cache['key'] == key
    assert refreshed == before


@pytest.mark.parametrize('field,value', [
    ('value', -2), ('availableFrom', CUTOFF), ('sourceRef', 'synthetic:revised-source'),
    ('eventSourceSha256', 'f'*64), ('eventId', 'synthetic:other'),
    ('reactionWindowSessions', 5), ('unit', 'OTHER'), ('unknownAnnotation', 'changed')])
def test_content_time_original_source_and_unknown_fields_still_invalidate(field, value):
    original = groups([research()]); cache = {}; compare(cache, original)
    previous = cache['sealedCandidates']
    changed = copy.deepcopy(original); changed['research'][0][field] = value
    result = compare(cache, changed)
    assert cache['sealedCandidates'] is not previous
    assert result == compare({}, changed, prepared=False)


@pytest.mark.parametrize('lane', ['states', 'conditions', 'reactions'])
def test_nonresearch_lanes_are_never_projected(lane):
    source = groups([]); source[lane] = [research()]
    projected = inputs.prepare(source)
    assert projected[lane] is source[lane]
    assert projected[lane][0]['sourceRowsHash'] == 'a'*64


@pytest.mark.parametrize('field,value', [
    ('availabilityBasis', 'ACTUAL_RECEIPT'), ('historicalVintageVerified', True),
    ('actualPublicationTimeVerified', True), ('actionAuthority', True),
    ('status', 'DATA_GATED'), ('sourceRowsHash', 'invalid'),
    ('sourceSha256', float('nan')), ('eventTimeBasis', 'VERIFIED_ACTUAL_PUBLICATION')])
def test_unmarked_real_or_malformed_research_keeps_full_rows(field, value):
    value_row = research(); value_row[field] = value
    projected = inputs.prepare(groups([value_row]))
    assert projected['research'][0] is value_row


@pytest.mark.parametrize('cross_lane', [False, True])
def test_hash_only_conflicting_revision_remains_rejected_after_warm_cache(cross_lane):
    initial = groups([research()]); cache = {}; compare(cache, initial)
    changed = copy.deepcopy(initial)
    other = {**changed['research'][0], 'sourceRowsHash': 'c'*64}
    changed['reactions' if cross_lane else 'research'].append(other)
    assert inputs.prepare(changed) is changed
    with pytest.raises(ValueError, match='conflicting_row_revision'):
        compare(cache, changed)
    with pytest.raises(ValueError, match='conflicting_row_revision'):
        compare({}, changed, prepared=False)


def test_identical_duplicates_and_iterator_are_conservatively_unchanged():
    source = groups([research(), research()]); assert inputs.prepare(source) is source
    source = groups(iter([research()])); assert inputs.prepare(source) is source


def test_caller_keeps_originals_and_observer_before_comparison_projection():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(__file__).with_name('scanner.py').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
        and any(isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                and child.func.attr == 'cached_index_comparison' for child in ast.walk(node)))
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    call = next(node for node in calls if isinstance(node.func, ast.Attribute)
                and node.func.attr == 'cached_index_comparison')
    arguments = {item.arg: ast.unparse(item.value) for item in call.keywords}
    for argument, lane in [('state_rows','states'), ('condition_rows','conditions'),
                           ('reaction_rows','reactions'), ('research_reaction_rows','research')]:
        assert arguments[argument] == f"comparison_inputs['{lane}']"
    projection = next(node for node in calls if ast.unparse(node.func) == 'argus_comparison_inputs.prepare')
    observation = next(node for node in calls if ast.unparse(node.func) == 'argus_comparison_preparation.begin')
    originals = next(node for node in calls if ast.unparse(node.func) == '_JP_ANALOG_RESEARCH_INPUTS.update')
    assert originals.lineno < observation.lineno < projection.lineno < call.lineno
