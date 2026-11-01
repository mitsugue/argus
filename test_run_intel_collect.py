import json

from scripts.run_intel_collect import run


def test_lost_response_reuses_id_and_waits_until_warming_finishes():
    calls, tick = [], [0]

    def request(**kwargs):
        body = json.loads(kwargs["data"])
        calls.append(body)
        if len(calls) == 1:
            raise TimeoutError("lost response")
        status = "done" if len(calls) == 4 else "running"
        return 200, json.dumps({"status": status, "runId": "test-run-1",
                                "finishedAt": "2026-09-09T00:00:00Z" if status == "done" else None,
                                "result": {"collected": 3, "stored": 40}})

    def sleep(n):
        tick[0] += n

    result = run(base="https://example.test", token="secret", request=request,
                 clock=lambda: tick[0], sleep=sleep, request_id="test-run-1")
    assert result["status"] == "done" and result["collected"] == 3
    assert calls[:2] == [{"async": True, "requestId": "test-run-1"}] * 2
    assert calls[2:] == [{"statusOnly": True, "requestId": "test-run-1"}] * 2
    assert "secret" not in json.dumps(result)


def test_failure_restart_or_legacy_endpoint_never_passes():
    for code, body in [(404, {}), (200, {"collected": 2}),
                       (200, {"status": "failed", "runId": "test-run-1", "errorClass": "RuntimeError"})]:
        result = run(base="https://example.test", token="secret", request_id="test-run-1",
                     request=lambda **kw: (code, json.dumps(body)))
        assert result["status"] == "failed"


def test_still_running_at_deadline_fails_and_poll_identity_cannot_change():
    tick = [0]
    def sleep(n):
        tick[0] += n
    result = run(base="https://example.test", token="secret", timeout=10,
                 request_id="test-run-1", clock=lambda: tick[0], sleep=sleep,
                 request=lambda **kw: (200, '{"status":"running","runId":"test-run-1"}'))
    assert result["errorClass"] == "collect_poll_timeout"
    replies = iter([{"status": "running", "runId": "active-run-2"},
                    {"status": "done", "runId": "different-run-3"}])
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps(next(replies))), sleep=lambda n: None)
    assert result["errorClass"] == "collect_run_identity_mismatch"


def test_all_failed_feeds_do_not_pass_just_because_the_worker_finished():
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps({"status": "done", "runId": "test-run-1",
                    "result": {"feeds": 2, "failedFeeds": ["feed-a", "feed-b"], "stored": 40}})))
    assert result["status"] == "failed" and result["errorClass"] == "all_intel_feeds_unavailable"


def test_admin_stage_details_are_not_added_to_workflow_output():
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps({"status": "done", "runId": "test-run-1",
                    "stage": "market_inputs", "completedStages": [{"stage": "news_feeds", "elapsedSeconds": 20}],
                    "result": {"collected": 3, "stored": 40}})))
    assert result["status"] == "done"
    assert "stage" not in result and "completedStages" not in result


def test_same_tracking_responses_supply_private_timings_without_extra_requests():
    calls, private = [], []
    replies = iter([{'status': 'running', 'runId': 'test-run-1', 'stage': 'pit_restore'},
                    {'status': 'done', 'runId': 'test-run-1',
                     'completedStages': [{'stage': 'pit_restore', 'elapsedSeconds': 120.125}],
                     'result': {'stored': 4}}])
    def request(**kwargs):
        calls.append(json.loads(kwargs['data']))
        return 200, json.dumps(next(replies))
    result = run(base='https://example.test', token='secret', request_id='test-run-1',
                 request=request, sleep=lambda _: None, private_timing=private.append)
    assert len(calls) == 2 and calls[1] == {'requestId': 'test-run-1', 'statusOnly': True}
    assert result['status'] == 'done' and 'completedStages' not in result
    assert private[0]['available'] is False
    assert private[1]['completedStages'] == [{'stage': 'pit_restore', 'elapsedSeconds': 120.125}]


def test_private_projection_accepts_only_fixed_stage_names_seconds_and_timestamps():
    from scripts.run_intel_collect import private_timing_record
    value = private_timing_record({'status': 'done', 'startedAt': '2026-10-29T00:00:00Z',
        'finishedAt': 'secret', 'stage': ['secret'], 'token': 'secret',
        'completedStages': [{'stage': 'news_feeds', 'elapsedSeconds': 1.25, 'body': 'secret'},
                            {'stage': 'secret', 'elapsedSeconds': 20},
                            {'stage': 'pit_restore', 'elapsedSeconds': True},
                            {'stage': 'pit_backup', 'elapsedSeconds': float('nan')} ]})
    assert value['completedStages'] == [{'stage': 'news_feeds', 'elapsedSeconds': 1.25}]
    assert value['finishedAt'] is None and value['stage'] is None
    assert 'secret' not in json.dumps(value) and value['available'] is True
    assert private_timing_record({'completedStages': {'secret': 2}})['available'] is False


def test_feature_substages_survive_only_the_private_timing_projection():
    from scripts.run_intel_collect import private_timing_record
    import scanner
    names = ['pit_feature_sources', 'pit_feature_ledger', 'pit_feature_reconcile',
             'pit_feature_build', 'pit_feature_persist']
    assert set(names) <= scanner._INTEL_COLLECT_STAGES
    tracked = {'status': 'done', 'runId': 'test-run-1', 'stage': names[-1],
               'result': {'stored': 4}, 'completedStages': [
                   {'stage': name, 'elapsedSeconds': i + 0.25, 'body': 'private-test-value'}
                   for i, name in enumerate(names)]}
    private = private_timing_record(tracked)
    assert [r['stage'] for r in private['completedStages']] == names
    assert [r['elapsedSeconds'] for r in private['completedStages']] == [i + .25 for i in range(5)]
    assert 'private-test-value' not in json.dumps(private)
    public = run(base='https://example.test', token='secret', request_id='test-run-1',
                 request=lambda **kw: (200, json.dumps(tracked)))
    assert public['status'] == 'done' and 'completedStages' not in public and 'stage' not in public


def test_private_timing_file_is_separate_and_symlink_does_not_overwrite(tmp_path):
    import pytest
    from scripts.run_intel_collect import save_private_timing
    target = tmp_path / 'private/timing.json'
    save_private_timing(target, {'available': False})
    assert target.stat().st_mode & 0o777 == 0o600
    prior = target.read_bytes()
    link = tmp_path / 'link'
    link.symlink_to(target)
    with pytest.raises(ValueError):
        save_private_timing(link, {'available': True})
    assert target.read_bytes() == prior


def test_main_cannot_claim_timing_saved_after_diagnostic_write_failure(monkeypatch, tmp_path, capsys):
    import scripts.run_intel_collect as collector
    def fake_run(**kw):
        kw['private_timing']({'available': True})
        return {'status': 'done'}
    def fail(*a):
        raise OSError('secret')
    monkeypatch.setattr(collector, 'run', fake_run)
    monkeypatch.setattr(collector, 'save_private_timing', fail)
    assert collector.main(['--private-timing-output', str(tmp_path / 'timing.json')]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value == {'status': 'done', 'privateTimingSaved': False, 'privateTimingAvailable': False,
                     'privateRuntimeSaved': False, 'privateRuntimeAvailable': False}


def runtime_fixture():
    return {'currentRssMib': 1000, 'peakRssMib': 1200,
        'owner': 'owner-test-value', 'token': 'secret-test-value',
        'intelCollect': {'currentRun': {'startedAt': '2026-11-01T00:00:00Z',
            'finishedAt': '2026-11-01T00:01:00Z', 'status': 'done', 'trigger': 'resident',
            'completedStages': [{'stage': 'pit_research', 'elapsedSeconds': 30}]}},
        'indexResearch': {'lastStartedAt': '2026-11-01T00:00:20Z',
            'lastCompletedAt': '2026-11-01T00:00:50Z', 'persistenceStatus': 'VERIFIED',
            'outcomes': {'comparison:N225:1': {'status': 'available', 'elapsedSeconds': 30,
                'cpuSeconds': 29.5, 'calibrationStatus': 'REUSED', 'body': 'owner-test-value'},
                'owner-test-value': {'cpuSeconds': 10}}}}


def test_runtime_projection_is_closed_and_does_not_infer_collection_cpu_ownership():
    from scripts.run_intel_collect import private_runtime_record
    raw = runtime_fixture()
    expected = {'startedAt': '2026-11-01T00:00:00Z', 'finishedAt': '2026-11-01T00:01:00Z'}
    value = private_runtime_record(raw, expected)
    assert value['available'] and value['collectionTimingBoundsMatch']
    assert value['researchWindowWithinExpectedCollection'] is True
    assert value['research']['outcomes']['comparison:N225:1']['cpuSeconds'] == 29.5
    assert value['observedCollection']['trigger'] == 'resident'
    assert value['scope'] == 'LATEST_GLOBAL_RESEARCH_OBSERVATION'
    assert 'owner-test-value' not in json.dumps(value) and 'secret-test-value' not in json.dumps(value)
    raw['intelCollect']['currentRun']['startedAt'] = '2026-11-01T00:00:01Z'
    raw['indexResearch']['lastStartedAt'] = '2026-10-31T23:59:00Z'
    value = private_runtime_record(raw, expected)
    assert not value['collectionTimingBoundsMatch']
    assert value['researchWindowWithinExpectedCollection'] is False
    raw['indexResearch']['outcomes']['comparison:N225:1'].update(cpuSeconds=float('nan'),
        elapsedSeconds=True, calibrationStatus={'secret': 1}, status=['owner-test-value'])
    value = private_runtime_record(raw, expected)
    row = value['research']['outcomes']['comparison:N225:1']
    assert row == {'cpuSeconds': None, 'elapsedSeconds': None, 'calibrationStatus': None, 'status': None}
    assert value['available'] is False
    raw['currentRssMib'] = 10 ** 1000
    assert private_runtime_record(raw, expected)['currentRssMib'] is None


def test_existing_runtime_readback_retains_closed_memory_and_allocator_identity_only():
    from scripts.run_intel_collect import private_runtime_record
    raw = runtime_fixture()
    raw['allocatorReclaim'] = {'startupPolicy': {'backendBuildSha': 'a' * 40,
        'backendVersion': '1.2.3', 'pythonAllocator': {'allocatorName': 'malloc'},
        'token': 'private-memory-sentinel'}}
    raw['operationAttribution'] = {'processIdentity': {'instanceId': 'b' * 32, 'pid': 123},
        'currentMemory': {'capturedAt': '2026-11-01T00:01:00Z',
            'smapsRollup': {'swapBytes': 0},
            'process': {'vmRssBytes': 500, 'vmHwmBytes': 600, 'owner': 'private-memory-sentinel'},
            'cgroup': {'memoryCurrentBytes': 800, 'memoryPeakBytes': 900,
                       'memoryMaxBytes': 2147483648, 'events': {'max': 2, 'oom_kill': 0}},
            'allocatorMetrics': {'allocatedBytes': 300, 'freeBytes': 100, 'mmapBytes': 5},
            'token': 'private-memory-sentinel'}}
    value = private_runtime_record(raw, {})['memoryObservation']
    assert value['backendSha'] == 'a' * 40 and value['backendVersion'] == '1.2.3'
    assert value['processInstanceId'] == 'b' * 32 and value['pid'] == 123
    assert value['allocatorName'] == 'malloc'
    assert value['swapBytes'] == 0
    assert value['process']['vmHwmBytes'] == 600
    assert value['cgroup']['memoryMaxBytes'] == 2147483648
    assert value['cgroup']['events']['oom_kill'] == 0
    assert value['cgroup']['events']['oom'] is None
    assert 'private-memory-sentinel' not in json.dumps(value)
    raw['operationAttribution']['processIdentity'].update(instanceId='private-memory-sentinel', pid=True)
    raw['operationAttribution']['currentMemory']['cgroup']['memoryMaxBytes'] = 2**100
    raw['allocatorReclaim']['startupPolicy'].update(backendBuildSha='A' * 40, backendVersion='private-memory-sentinel')
    raw['allocatorReclaim']['startupPolicy']['pythonAllocator']['allocatorName'] = {'secret': 1}
    value = private_runtime_record(raw, {})['memoryObservation']
    assert value['pid'] is None and value['processInstanceId'] is None
    assert value['backendSha'] is None and value['backendVersion'] is None
    assert value['allocatorName'] is None and value['cgroup']['memoryMaxBytes'] is None
    assert 'private-memory-sentinel' not in json.dumps(value)


def test_private_runtime_is_one_get_after_original_collection_with_no_stdout_details():
    calls, records = [], []
    tracked = {'status': 'done', 'runId': 'test-run-1',
        'startedAt': '2026-11-01T00:00:00Z', 'finishedAt': '2026-11-01T00:01:00Z'}
    def request(**kw):
        calls.append(kw)
        return 200, json.dumps(runtime_fixture() if kw['method'] == 'GET' else tracked)
    result = run(base='https://example.test', token='secret-test-value', request_id='test-run-1',
                 request=request, private_runtime=records.append)
    assert [c['method'] for c in calls] == ['POST', 'GET']
    assert calls[1]['url'] == 'https://example.test/api/argus/admin/memory-attribution'
    assert calls[1]['data'] is None and calls[1]['timeout'] <= 15
    assert records[0]['available'] and result['status'] == 'done'
    for value in ('cpuSeconds', 'resident', 'secret-test-value', 'owner-test-value'):
        assert value not in json.dumps(result)


def test_private_runtime_respects_remaining_budget_without_restarting_completed_work():
    calls, records, tick = [], [], [0]
    def request(**kw):
        calls.append(kw)
        tick[0] = 11
        return 200, '{"status":"done","runId":"test-run-1"}'
    result = run(base='https://example.test', token='secret', timeout=10, clock=lambda: tick[0],
        request=request, request_id='test-run-1', private_runtime=records.append)
    assert result['status'] == 'done' and len(calls) == 1
    assert records == [{'schemaVersion': 'argus-collect-private-runtime-v1',
                       'available': False, 'errorClass': 'runtime_budget_exhausted'}]


def test_private_runtime_timeout_is_capped_by_remaining_collection_budget():
    calls, tick, records = [], [0], []
    def request(**kw):
        calls.append(kw)
        if kw['method'] == 'GET':
            assert kw['timeout'] == 2
            raise TimeoutError('secret-test-value')
        tick[0] = 8
        return 200, '{"status":"failed","runId":"test-run-1","errorClass":"collector_failed"}'
    result = run(base='https://example.test', token='secret', timeout=10,
        clock=lambda: tick[0], request=request, request_id='test-run-1', private_runtime=records.append)
    assert result['status'] == 'failed' and result['errorClass'] == 'collector_failed'
    assert [c['method'] for c in calls] == ['POST', 'GET']
    assert records[0]['errorClass'] == 'runtime_transport_or_json_error'
    assert 'secret-test-value' not in json.dumps(records)


def test_private_runtime_failure_and_sink_failure_never_change_collection_result():
    for reply in [(403, 'secret-test-value'), (200, 'bad-json'), (200, 'x' * (1024 * 1024 + 1))]:
        calls, records = [], []
        def request(**kw):
            calls.append(kw['method'])
            return reply if kw['method'] == 'GET' else (200, '{"status":"done","runId":"test-run-1"}')
        result = run(base='https://example.test', token='secret', request=request,
            request_id='test-run-1', private_runtime=records.append)
        assert calls == ['POST', 'GET'] and result['status'] == 'done'
        assert records[0]['available'] is False and 'secret-test-value' not in json.dumps(records)
    def broken_sink(value):
        raise OSError('secret-test-value')
    assert run(base='https://example.test', token='secret',
        request=lambda **kw: (200, '{"status":"done","runId":"test-run-1"}'),
        request_id='test-run-1', private_runtime=broken_sink)['status'] == 'done'


def test_main_saves_runtime_only_in_sibling_private_file(monkeypatch, tmp_path, capsys):
    import scripts.run_intel_collect as collector
    def fake_run(**kw):
        kw['private_timing']({'available': True})
        kw['private_runtime'](collector.private_runtime_record(runtime_fixture(), {}))
        return {'status': 'done'}
    monkeypatch.setattr(collector, 'run', fake_run)
    target = tmp_path / 'collect-timing.json'
    assert collector.main(['--private-timing-output', str(target)]) == 0
    private = tmp_path / 'collect-timing-runtime.json'
    assert private.exists() and private.stat().st_mode & 0o777 == 0o600
    assert json.loads(private.read_text())['research']['outcomes']['comparison:N225:1']['cpuSeconds'] == 29.5
    stdout = capsys.readouterr().out
    assert json.loads(stdout)['privateRuntimeSaved'] is True
    assert 'cpuSeconds' not in stdout and 'owner-test-value' not in stdout


def test_failed_feed_names_are_kept_for_the_private_record():
    """2026-10-19: "2 of 20 feeds failed" could not say which two."""
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps({"status": "done", "runId": "test-run-1",
                    "result": {"feeds": 20, "failedFeeds": ["meti_official", "nikkei_web"], "stored": 40}})))
    assert result["status"] == "done" and result["failedFeedCount"] == 2
    assert result["failedFeeds"] == ["meti_official", "nikkei_web"]


def test_failed_feed_reasons_keep_fixed_codes_only():
    """2026-10-20: meti:release failed only in production; the reason was not recorded."""
    result = run(base="https://example.test", token="secret", request_id="test-run-1",
                 request=lambda **kw: (200, json.dumps({"status": "done", "runId": "test-run-1",
                    "result": {"feeds": 20, "failedFeeds": ["meti:release"], "stored": 40, "perFeed": [
                        {"feed": "meti:release", "ok": False, "httpStatus": 403, "errorClass": "http_unavailable",
                         "elapsedSeconds": 0.4, "fetched": 0, "body": "<html>secret</html>"},
                        {"feed": "boj:release", "ok": True, "httpStatus": 200, "errorClass": None}]}})))
    assert result["failedFeedReasons"] == [
        {"feed": "meti:release", "httpStatus": 403, "errorClass": "http_unavailable", "elapsedSeconds": 0.4}]
    assert "secret" not in json.dumps(result)


def test_joining_an_existing_collection_polls_its_original_identity():
    calls = []
    replies = iter([{"status": "running", "runId": "already-running"},
                    {"status": "done", "runId": "already-running", "result": {}}])
    def request(**kwargs):
        calls.append(json.loads(kwargs["data"]))
        return 200, json.dumps(next(replies))
    result = run(base="https://example.test", token="secret", request_id="new-request-1",
                 request=request, sleep=lambda _: None)
    assert result["status"] == "done" and result["runId"] == "already-running"
    assert calls == [{"async": True, "requestId": "new-request-1"},
                     {"statusOnly": True, "requestId": "already-running"}]
