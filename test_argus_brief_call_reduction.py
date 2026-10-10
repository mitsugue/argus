"""Offline call-path acceptance; synthetic receipts are never billed savings."""
import copy
import json

import pytest
import scanner
import argus_market_brief as mb
import argus_market_position_memory as position
from argus_explanation_contract import render_event_references
from test_argus_unified_brief import model_response
from test_argus_market_position_memory import NEWS, CALENDAR
from test_remote_recovery_publish import _reuse_inputs


def scheduled_brief(event=None):
    return mb.compose_brief(now_iso='2026-10-10T00:00:00Z', next_events=[event or {
        'eventId': 'cpi-fixture', 'title': '米CPI', 'eventTimeUtc': '2026-10-14T12:30:00Z'}])


def test_calendar_reference_renders_exact_jst_with_one_call_and_unchanged_gates(monkeypatch):
    calls = []
    def provider(user, **kwargs):
        context, raw = model_response(user)
        ref = next(f['evidenceId'] for f in context['facts'] if f['source'] == 'calendar')
        raw['view']['textJa'] = '物価の方向を確認します。'
        raw['reasons']['textJa'] = '発表後の市場反応を確認します。'
        raw['invalidation']['textJa'] = '物価の方向が変われば見直します。'
        raw['next']['textJa'] = '{event:' + ref + '}で物価の方向を確認します。'
        raw['next']['evidenceIds'] = [ref]
        calls.append(copy.deepcopy(raw))
        kwargs['diagnostic'].update(outcome='ok', returnedModel=scanner._OPENAI_MODEL,
            completedAt='2026-10-10T00:00:00Z', inputTokens=100, outputTokens=10,
            cachedInputTokens=25, estUsd=.001)
        return raw
    monkeypatch.setattr(scanner, '_openai_prose', provider)
    b = scheduled_brief(); b['unifiedContext'] = mb.unified_context(b)
    original = copy.deepcopy(b['unifiedContext'])
    result = scanner._market_brief_ai_polish(b)
    assert result['unifiedStatus'] == result['presentationStatus'] == 'GENERATED'
    assert len(calls) == 1
    assert result['unifiedSummary']['sections']['next']['textJa'] == '米CPI（2026/10/14 21:30（日本時間））で物価の方向を確認します。'
    assert result['unifiedContext'] == original
    assert result['aiDiagnostics']['callReduction']['correctionCalls'] == 0
    assert result['aiDiagnostics']['cachedInputTokens'] == 25
    assert result['aiModel'] == scanner._OPENAI_MODEL
    assert result['unifiedSummary']['actionAuthority'] is False


@pytest.mark.parametrize('event,expected', [
    ({'title':'会合','date':'2026-10-14'}, '会合（2026/10/14・時刻未公表）'),
    ({'title':'SQ','whenJa':'2026-10-09・寄付き基準'}, 'SQ（2026-10-09・寄付き基準）'),
    ({'title':'会合'}, '会合（日時未確認）')])
def test_source_precision_stays_missing_or_opening_reference(event, expected):
    context = mb.unified_context(scheduled_brief(event))
    ref = next(f['evidenceId'] for f in context['facts'] if f['source'] == 'calendar')
    raw = {'next': {'textJa':'{event:' + ref + '}を確認。', 'evidenceIds':[ref]}}
    assert render_event_references(raw, context)['next']['textJa'] == expected + 'を確認。'


@pytest.mark.parametrize('mutation,reason', [
    ('unknown', 'event_reference_unavailable'), ('uncited', 'event_reference_unavailable'),
    ('prior', 'event_reference_unavailable'), ('unverified', 'event_reference_unavailable'),
    ('malformed', 'event_reference_malformed'), ('noncalendar', 'event_reference_unavailable')])
def test_untrusted_event_tokens_fail_closed(mutation, reason):
    context = mb.unified_context(scheduled_brief())
    fact = next(f for f in context['facts'] if f['source'] == 'calendar'); ref = fact['evidenceId']
    text = '{event:' + ('unknown' if mutation == 'unknown' else ref) + '}'
    if mutation == 'malformed': text = '{event:' + ref
    refs = [] if mutation == 'uncited' else [ref]
    if mutation == 'prior': context['previousFacts'] = context.pop('facts'); context['facts'] = []
    if mutation == 'unverified': fact['verification'] = 'UNCONFIRMED'
    if mutation == 'noncalendar': fact['source'] = 'trusted_mail'
    with pytest.raises(ValueError, match=reason):
        render_event_references({'next': {'textJa':text, 'evidenceIds':refs}}, context)


def test_renderer_does_not_delete_invented_numbers_or_accept_empty_refusal():
    context = mb.unified_context(scheduled_brief())
    ref = next(f['evidenceId'] for f in context['facts'] if f['source'] == 'calendar')
    raw = {key:{'textJa':'確認します。', 'evidenceIds':[ref], 'kind':'INFERENCE'} for key in mb.UNIFIED_SECTIONS}
    raw['impact'] = raw['changes'] = {'textJa':'未確認。','evidenceIds':[],'kind':'UNKNOWN'}
    raw['next']['textJa'] = '{event:' + ref + '}で99%の上昇を確認。'
    rendered = render_event_references(raw, context)
    diag = {}
    assert '99%' in rendered['next']['textJa']
    assert mb.validate_unified_ai(rendered, context, diagnostic=diag) is None
    assert diag['reason'] == 'unsupported_numeric_tokens'
    for unavailable in (None, {}, {'refusal':'unavailable'}):
        assert mb.validate_unified_ai(render_event_references(unavailable, context), context) is None


def test_ai_assessment_keeps_history_display_but_does_not_change_external_digest(monkeypatch):
    brief, internals = _reuse_inputs(monkeypatch)
    memory = position.empty(); position.ingest_news(memory, NEWS)
    before = position.snapshot(memory, now_iso='2026-10-03T02:00:00Z', scheduled_events=CALENDAR)
    brief['marketPosition'] = before; brief['facts'] = position.explanation_facts(before)
    digest = scanner._market_brief_generation_input_digest(brief, internals)
    view = {'themeId':'US_POLICY_RATE', 'expectationJa':'物価の落ち着きを期待', 'fearJa':'物価の再加速を警戒',
            'triggerJa':'次の発表', 'evidenceIds':['fixture'], 'kind':'INFERENCE'}
    assert position.ingest_views(memory, [view], context_id='fixture', generated_at='2026-10-03T03:00:00Z') == 1
    after = position.snapshot(memory, now_iso='2026-10-03T03:00:00Z', scheduled_events=CALENDAR)
    assert after['entryCount'] == before['entryCount'] + 1
    assert any(t['view'] for t in after['themes'])
    assert position.explanation_facts(after) == brief['facts']
    brief['marketPosition'] = after
    assert scanner._market_brief_generation_input_digest(brief, internals) == digest
    original = json.dumps(memory, sort_keys=True)
    quiet = position.snapshot(memory, now_iso='2026-11-03T03:00:00Z', scheduled_events=CALENDAR)
    brief['marketPosition'] = quiet; brief['facts'] = position.explanation_facts(quiet)
    assert scanner._market_brief_generation_input_digest(brief, internals) != digest
    assert json.dumps(memory, sort_keys=True) == original
    position.ingest_news(memory, [dict(NEWS[0], eventId='new-official-fixture', sourceReceivedAt='2026-10-03T04:00:00Z',
                                     headlineJa='FRB高官、追加利上げ方針を訂正')])
    newer = position.snapshot(memory, now_iso='2026-10-03T04:00:00Z', scheduled_events=CALENDAR)
    brief['marketPosition'] = newer; brief['facts'] = position.explanation_facts(newer)
    assert scanner._market_brief_generation_input_digest(brief, internals) != digest


def test_many_ai_views_cannot_push_latest_external_evidence_out_of_recent_window():
    memory = position.empty(); position.ingest_news(memory, NEWS)
    before = position.snapshot(memory, now_iso='2026-10-03T02:00:00Z')
    for n in range(position.RECENT_ENTRIES + 2):
        position.ingest_views(memory, [{'themeId':'US_POLICY_RATE','expectationJa':f'fixture {n}',
            'fearJa':'警戒','triggerJa':'発表','evidenceIds':['fixture'],'kind':'INFERENCE'}],
            context_id=f'fixture-{n}', generated_at='2026-10-03T03:00:00Z')
    after = position.snapshot(memory, now_iso='2026-10-03T03:00:00Z')
    assert position.explanation_facts(after) == position.explanation_facts(before)
    assert position.generation_inputs(after) == position.generation_inputs(before)


def test_ai_only_change_reuses_complete_edition_without_paid_call(monkeypatch):
    brief, internals = _reuse_inputs(monkeypatch)
    memory = position.empty(); position.ingest_news(memory, NEWS)
    view = position.snapshot(memory, now_iso='2026-10-03T02:00:00Z')
    brief['marketPosition'] = view; brief['facts'] = position.explanation_facts(view)
    previous = {**copy.deepcopy(brief), 'unifiedStatus':'GENERATED', 'presentationStatus':'GENERATED',
                'unifiedSummary':{'fixture':'frozen edition'}, 'calculationSnapshots':{'5':{'fixture':100}}}
    state = {'lastSuccessful':copy.deepcopy(previous),
             'generationInputDigest':scanner._market_brief_generation_input_digest(brief, internals)}
    monkeypatch.setattr(scanner, '_MARKET_BRIEF', state)
    position.ingest_views(memory, [{'themeId':'US_POLICY_RATE','expectationJa':'物価の落ち着き',
        'fearJa':'物価の再加速','triggerJa':'次の発表','evidenceIds':['fixture'],'kind':'INFERENCE'}],
        context_id='fixture', generated_at='2026-10-03T03:00:00Z')
    brief['marketPosition'] = position.snapshot(memory, now_iso='2026-10-03T03:00:00Z')
    brief['facts'] = position.explanation_facts(brief['marketPosition'])
    assert mb.unified_context(brief)['priorAssessments'][0]['assessment']['fearJa'] == '物価の再加速'
    monkeypatch.setattr(scanner, '_compose_market_brief', lambda:copy.deepcopy(brief))
    monkeypatch.setattr(scanner, '_jp_market_internals_cached', lambda:internals)
    def forbidden(*args, **kwargs): raise AssertionError('AI-only changes must not generate or compute')
    for name in ('_market_brief_ai_polish', '_jp_market_comparison_cached', '_market_brief_history_save'):
        monkeypatch.setattr(scanner, name, forbidden)
    result = scanner._market_brief_refresh(allow_ai=True)
    assert result['generationReuse']['newAiCalls'] == 0
    assert result['unifiedSummary'] == previous['unifiedSummary']
    assert result['calculationSnapshots'] == previous['calculationSnapshots']
    assert state['lastSuccessful'] == previous


def test_bad_event_reference_gets_only_one_correction_and_keeps_both_receipts(monkeypatch):
    calls = []
    def provider(user, **kwargs):
        context, raw = model_response(user)
        for key in ('view', 'reasons', 'next', 'invalidation'):
            raw[key]['textJa'] = '物価の方向を確認します。'
        ref = next(f['evidenceId'] for f in context['facts'] if f['source'] == 'calendar')
        raw['next']['textJa'] = '{event:' + (ref if calls else 'missing-fixture') + '}を確認。'
        raw['next']['evidenceIds'] = [ref]
        calls.append(user)
        kwargs['diagnostic'].update(outcome='ok', returnedModel=scanner._OPENAI_MODEL, estUsd=.001)
        return raw
    monkeypatch.setattr(scanner, '_openai_prose', provider)
    b = scheduled_brief(); b['unifiedContext'] = mb.unified_context(b)
    result = scanner._market_brief_ai_polish(b)
    assert len(calls) == 2 and result['unifiedStatus'] == 'GENERATED'
    assert result['aiDiagnostics']['totalEstUsd'] == .002
    assert result['aiDiagnostics']['attempts'][0]['validation']['reason'] == 'event_reference_unavailable'
    assert result['aiDiagnostics']['callReduction']['correctionCalls'] == 1
