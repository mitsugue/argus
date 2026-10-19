"""2026-10-19: the internals document is saved once per edition (on the "5" snapshot).

Four identical copies were about 250 KB (26%) of every saved edition."""
import inspect

import argus_owner_dialogue as dialogue
import scanner


def _brief(snapshots, horizons):
    return {"calculationSnapshots": snapshots, "unifiedContext": {"facts": [
        {"source": "market_internals_calculation",
         "provenance": {"eventId": f"market-internals-{h}", "sourceRowSha256": "a" * 64}} for h in horizons]}}


DOC = {"schemaVersion": "jp-market-internals-v1", "actionAuthority": False, "evidenceId": "a" * 64,
       "periods": {"1": {"p": 1}, "5": {"p": 5}, "10": {"p": 10}, "20": {"p": 20}}}


def test_other_horizons_read_the_one_copy_on_the_five_session_snapshot():
    brief = _brief({"1": {}, "5": {"marketInternals": DOC}, "10": {}, "20": {}}, (1, 5, 10, 20))
    assert [dialogue.market_internals(brief, h) for h in (1, 5, 10, 20)] == [{"p": 1}, {"p": 5}, {"p": 10}, {"p": 20}]


def test_older_editions_with_a_copy_per_horizon_still_read():
    brief = _brief({str(h): {"marketInternals": DOC} for h in (1, 5, 10, 20)}, (1, 5, 10, 20))
    assert dialogue.market_internals(brief, 20) == {"p": 20}


def test_the_brief_keeps_one_copy():
    source = inspect.getsource(scanner)
    start = source.index('holder = "5" if isinstance(calculations.get("5"), dict) else None')
    block = source[start:start + 400]
    assert 'calculation.pop("marketInternals", None)' in block
    assert 'for calculation in calculations.values():\n        calculation["marketInternals"] = internals' not in source
