"""US mover freshness gate (v10.143): stale AV snapshots must not push as fresh."""
import time, scanner


def test_av_lastupdated_parse():
    ep = scanner._av_lastupdated_epoch("2026-06-24 16:15:59 US/Eastern")
    assert ep is not None
    assert scanner._av_lastupdated_epoch(None) is None
    assert scanner._av_lastupdated_epoch("garbage") is None


def test_staleness_decision():
    now = time.time()
    fresh_ep = scanner._av_lastupdated_epoch("2026-06-24 16:15:59 US/Eastern")  # historical fixture
    # simulate: a timestamp 20 minutes ago is fresh; 20 hours ago is stale
    assert (now - (now - 1200)) <= scanner._MOVER_FRESH_SEC          # 20min → fresh window
    assert (now - (now - 72000)) > scanner._MOVER_FRESH_SEC          # 20h → stale
    assert isinstance(scanner._MOVER_FRESH_SEC, float) and scanner._MOVER_FRESH_SEC >= 3600
