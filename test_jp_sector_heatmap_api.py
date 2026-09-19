import scanner
from jp_sector_heatmap_runtime import Runtime

def test_public_route_uses_snapshot_without_provider_calls(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('public read must not acquire')
    runtime=Runtime(forbidden)
    monkeypatch.setattr(scanner,'_JP_SECTOR_HEATMAP',runtime)
    with scanner.app.test_client() as client:
        for _ in range(2):
            response=client.get('/api/argus/sector-heatmap')
            assert response.status_code==200
            assert response.json['actionAuthority'] is False
            assert len(response.json['rows'])==8
    assert runtime.last_attempt==0

def test_existing_durable_writer_restores_source_times(monkeypatch,tmp_path):
    monkeypatch.setattr(scanner,'_DURABILITY_PATHS',{'root':str(tmp_path)})
    monkeypatch.setattr(scanner,'_cost_policy_durable_enabled',lambda:True)
    monkeypatch.setattr(scanner,'_JP_SECTOR_HEATMAP',None)
    runtime=scanner._jp_sector_heatmap_runtime()
    body={'quotes':{'1631':{'price':110,'sourceTimestamp':'2026-09-18T06:30:00Z','source':'fixture'}},
          'histories':{'1631':{'2026-09-17':100}},'historyDates':{'1631':'2026-09-18'}}
    runtime.save(body)
    monkeypatch.setattr(scanner,'_JP_SECTOR_HEATMAP',None)
    restored=scanner._jp_sector_heatmap_runtime()
    assert restored.published==body
    assert restored.quotes['1631']['sourceTimestamp']=='2026-09-18T06:30:00Z'
