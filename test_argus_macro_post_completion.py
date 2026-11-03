"""Only the target's saved current-result explanation completes a watch request."""
from copy import deepcopy

import pytest

import argus_macro_event_store as store
from argus_macro_release_watch import post_analysis_saved


def completed():
    actual = {'available': True, 'source': 'FixtureStats', 'metrics': {'value': 100}}
    return {'actual': actual, 'post': {
        'generatedAt': '2026-10-02T20:32:00Z', 'verdict': 'partial',
        'reactionWindow': '+8h', 'actualRevisionId': store.actual_revision_id(actual)}}


@pytest.mark.parametrize('failure', ['no_post', 'earlier_window', 'other_result',
                                   'no_generation_time', 'not_available', 'save_failed'])
def test_unfinished_analysis_cannot_complete_request(failure):
    record = completed(); persistence = {'status': 'saved'}
    if failure == 'no_post': record.pop('post')
    if failure == 'earlier_window': record['post']['reactionWindow'] = '+60m'
    if failure == 'other_result': record['post']['actualRevisionId'] = 'another-result'
    if failure == 'no_generation_time': record['post']['generatedAt'] = None
    if failure == 'not_available': record['post']['verdict'] = 'not_available'
    if failure == 'save_failed': persistence['status'] = 'failed'
    before = deepcopy(record)
    assert not post_analysis_saved(record, '+8h', persistence)
    assert record == before


@pytest.mark.parametrize('verdict', ['partial', 'not_scoreable'])
def test_saved_later_window_for_current_result_completes_request(verdict):
    record = completed(); record['post']['verdict'] = verdict
    assert post_analysis_saved(record, '+60m', {'status': 'saved'})
    assert post_analysis_saved(record, '+8h', {'status': 'saved'})


def test_current_result_revision_invalidates_old_analysis_without_changing_it():
    record = completed(); prior = deepcopy(record['post'])
    record['actual']['metrics']['value'] = 101
    assert not post_analysis_saved(record, '+8h', {'status': 'saved'})
    assert record['post'] == prior
