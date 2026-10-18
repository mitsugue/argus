"""Owner-only export of the comparison's inputs for the offline study (2026-10-19)."""


def test_analog_inputs_are_owner_only_and_on_request(monkeypatch):
    import scanner
    monkeypatch.setattr(scanner, '_ARGUS_ADMIN_TOKEN', 'synthetic-admin')
    monkeypatch.setattr(scanner, '_JP_ANALOG_RESEARCH_INPUTS',
                        {'cutoff': '2026-10-19T00:00:00Z', 'horizon': 5, 'sessions': ['2026-10-16'],
                         'stateRows': ({'seriesId': 'vix.level', 'date': '2026-10-16', 'value': 15.0},)})
    with scanner.app.test_client() as client:
        assert client.get('/api/argus/admin/memory-attribution?analog-inputs=1').status_code == 401
        headers = {'X-ARGUS-ADMIN-TOKEN': 'synthetic-admin'}
        assert 'analogResearchInputs' not in client.get('/api/argus/admin/memory-attribution', headers=headers).get_json()
        body = client.get('/api/argus/admin/memory-attribution?analog-inputs=1', headers=headers).get_json()
        assert body['analogResearchInputs']['stateRows'] == [{'seriesId': 'vix.level', 'date': '2026-10-16', 'value': 15.0}]
        assert body['analogResearchInputs']['sessions'] == ['2026-10-16']
