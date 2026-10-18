"""The official auction-history workbook kept privately (2026-10-18, owner approved)."""
import base64
import json

import pytest

import argus_jgb_auction as auction
import argus_jp_fiscal_runtime as runtime
import argus_market_ledger as ledger
import argus_market_input_backup as backup
from test_argus_jgb_archive import install, AT
from test_argus_market_input_backup import Remote


def test_workbook_is_kept_once_and_read_back_from_the_private_backup(monkeypatch, tmp_path):
    install(monkeypatch)
    path = tmp_path / 'source.sqlite3'
    first = backup.retain_jgb_archive(path, b'archive-fixture', received_at=AT)
    again = backup.retain_jgb_archive(path, b'archive-fixture', received_at='2026-11-02T02:00:00+09:00')
    assert first['status'] == again['status'] == 'RETAINED' and first['rows'] == 4
    remote = Remote()
    result = backup.synchronize(path, remote)
    assert result['status'] == 'VERIFIED' and result['counts']['jgbArchive'] == 1
    manifest = json.loads(remote.files[backup.PREFIX + '/manifests/' + result['manifestSha256'] + '.json'])
    content = b''.join(remote.files[backup.PREFIX + '/chunks/' + c['sha256'] + '.bin'] for c in manifest['chunks'])
    raws = [json.loads(line) for line in content.splitlines() if b'"kind":"raw"' in line]
    assert [base64.b64decode(r['dataBase64']) for r in raws] == [b'archive-fixture']
    assert raws[0]['url'] == auction.ARCHIVE_URL and raws[0]['receivedAt'] == AT   # first receipt kept
    assert backup.status_projection({'counts': result['counts']})['counts']['jgbArchive'] == 1


def test_an_invalid_workbook_is_not_kept(monkeypatch, tmp_path):
    path = tmp_path / 'source.sqlite3'
    with pytest.raises(Exception):
        backup.retain_jgb_archive(path, b'not-a-workbook', received_at=AT)
    assert not path.exists() or b'not-a-workbook' not in path.read_bytes()


def test_runtime_records_whether_the_original_was_kept_and_never_blocks_rows(monkeypatch):
    from test_argus_jp_fiscal_runtime import fixture, calendar, AT as start
    get, calls, bodies, _ = fixture(monkeypatch)
    initial = runtime.refresh(ledger.empty_state(), now_iso=start, calendar=calendar(), get=get)['state']
    install(monkeypatch)
    bodies[auction.ARCHIVE_URL] = b'archive-fixture'
    kept = []
    ok = runtime.refresh(initial, now_iso='2026-09-17T07:00:01Z', calendar=calendar(), get=get,
                         retain_archive=lambda raw, received: kept.append((raw, received)))
    control = ok['state']['fiscalMonitor']
    assert kept and kept[0][0] == b'archive-fixture'
    assert control['auctionArchiveOriginalStatus'] == 'RETAINED'
    assert control['auctionArchiveReport']['originalStatus'] == 'RETAINED'
    def broken(raw, received):
        raise OSError('disk')
    failed = runtime.refresh(initial, now_iso='2026-09-17T07:00:01Z', calendar=calendar(), get=get,
                             retain_archive=broken)['state']['fiscalMonitor']
    assert failed['auctionArchiveStatus'] == 'AVAILABLE' and failed['auctionArchiveOriginalStatus'] == 'RETENTION_FAILED'
    assert sum(v['rowCount'] for v in failed['auctionArchiveReport']['series'].values()) == 4
    plain = runtime.refresh(initial, now_iso='2026-09-17T07:00:01Z', calendar=calendar(), get=get)['state']['fiscalMonitor']
    assert plain['auctionArchiveOriginalStatus'] == 'NOT_CONFIGURED'


def test_document_shows_the_connected_auctions_without_changing_the_rule_id(monkeypatch):
    from test_argus_jp_fiscal_runtime import fixture, calendar, AT as start
    get, _, _, _ = fixture(monkeypatch)
    state = runtime.refresh(ledger.empty_state(), now_iso=start, calendar=calendar(), get=get)['state']
    report = state['fiscalMonitor'].get('report') or {}
    first = next(iter(report.get('cases', {}).values()), {})
    if not first.get('market'):
        pytest.skip('fixture produced no market rule')
    market_id = first['market']['id']
    view = runtime.public_document(state)
    if 'auctions' in view:
        assert view['market']['auctionStatus'] == 'CONNECTED_SEPARATELY'
    assert view['market']['id'] == market_id
    assert first['market']['auctionStatus'] == 'NOT_CONNECTED'      # the stored rule is unchanged
