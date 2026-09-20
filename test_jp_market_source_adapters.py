import copy
import unittest

from jp_market_source_adapters import normalize_jquants_margin_snapshot as normalize
from jp_market_dynamics import credit_dynamics


class MarginSourceTests(unittest.TestCase):
    def setUp(self):
        self.options = dict(instrument_id="1570", observed_at="2026-09-12T01:12:11Z",
                            response_sha256="a" * 64, volume_unit="UNITS")
        self.rows = [{"Date": "2026-08-28", "Code": "15700", "LongVol": 120, "ShrtVol": 20,
                      "LongStdVol": 80, "LongNegVol": 40, "ShrtStdVol": 18, "ShrtNegVol": 2},
                     {"Date": "2026-09-04", "Code": "15700", "LongVol": 150, "ShrtVol": 15}]

    def result(self, rows=None, **extra):
        return normalize({"data": self.rows if rows is None else rows, **extra}, **self.options)

    def test_balance_components_and_receipt_provenance(self):
        result = self.result()
        self.assertEqual(len(result["rows"]), 8)
        self.assertEqual(result["status"], "AVAILABLE")
        for row in result["rows"]:
            self.assertEqual(row["knownAt"], "2026-09-12T01:12:11+00:00")
            self.assertIsNone(row["publishedAt"])
            self.assertFalse(row["creditTermKnown"])
        self.assertEqual(self.rows[0]["LongVol"], 120)

    def test_current_dynamics_and_no_historical_backdating(self):
        rows = self.result()["rows"]
        args = dict(instrument_id="1570", balance_kind="WEEKLY_MARGIN",
                    long_series="margin.long_balance", short_series="margin.short_balance")
        before = credit_dynamics(rows, cutoff="2026-09-11T23:00:00Z", **args)
        self.assertIsNone(before["current"])
        current = credit_dynamics(rows, cutoff="2026-09-12T02:00:00Z", **args)
        self.assertEqual(current["current"]["ratio"], 10)
        self.assertEqual(current["change"]["ratioChange"], 4)
        self.assertAlmostEqual(current["change"]["longContribution"] + current["change"]["shortContribution"], 4)

    def test_wrong_code_and_invalid_totals(self):
        for patch in ({"Code": "72030"}, {"LongVol": None}, {"LongVol": True},
                      {"LongVol": -1}, {"LongVol": float("inf")}, {"LongVol": 1.5}):
            rows = [dict(self.rows[1], **patch)]
            self.assertEqual(self.result(rows)["rows"], [])

    def test_component_disagreement_not_silently_accepted(self):
        rows = copy.deepcopy(self.rows[:1]); rows[0]["LongNegVol"] = 41
        self.assertEqual(self.result(rows)["rejectedRows"][0]["reason"], "inconsistent_credit_components")

    def test_duplicate_period_invalidates_both(self):
        result = self.result([self.rows[1], dict(self.rows[1], LongVol=180)])
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["status"], "PARTIAL")

    def test_future_period_rejected(self):
        self.assertEqual(self.result([dict(self.rows[1], Date="2026-09-18")])["rows"], [])

    def test_zero_balances_preserved_without_finite_ratio(self):
        result = self.result([dict(self.rows[1], LongVol=0, ShrtVol=0)])
        self.assertEqual(len(result["rows"]), 2)
        self.assertTrue(all(row["value"] == 0 for row in result["rows"]))

    def test_missing_unit_receipt_or_digest_cannot_be_invented(self):
        for key, value in (("volume_unit", "JPY"), ("observed_at", ""), ("observed_at", "2026-09-12"), ("response_sha256", "")):
            with self.assertRaises(ValueError):
                normalize({"data": self.rows}, **{**self.options, key: value})

    def test_pagination_is_explicitly_partial(self):
        result = self.result(pagination_key="opaque-cursor")
        self.assertEqual(result["status"], "PARTIAL")
        self.assertNotIn("opaque-cursor", str(result))

    def test_empty_data_is_unavailable(self):
        self.assertEqual(self.result([])["status"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()


def test_durable_margin_rechecks_rolloff_and_correction_keep_original_prefix(tmp_path):
    import json
    import hashlib
    import sqlite3
    from jp_market_source_adapters import retain_margin_snapshot, restore_margin_snapshot
    path = tmp_path / 'sources.sqlite3'
    def candidate(rows, at):
        raw = json.dumps({'data': rows}).encode()
        return normalize({'data': rows}, instrument_id='1570', observed_at=at,
                         response_sha256=hashlib.sha256(raw).hexdigest(), volume_unit='UNITS'), raw
    rows = [{'Date': '2026-08-28', 'Code': '15700', 'LongVol': 120, 'ShrtVol': 20},
            {'Date': '2026-09-04', 'Code': '15700', 'LongVol': 150, 'ShrtVol': 15}]
    first, raw = candidate(rows, '2026-09-12T01:00:00Z')
    saved = retain_margin_snapshot(first, path=path, raw=raw)
    original = copy.deepcopy(saved['rows'])
    repeat, raw = candidate(rows, '2026-09-12T02:00:00Z')
    repeated = retain_margin_snapshot(repeat, path=path, raw=raw)
    assert repeated['rows'] == original
    assert repeated['observedAt'] != saved['observedAt']
    # Simulate restart, a rolling source and a received correction.
    corrected, raw = candidate([dict(rows[1], LongVol=180)], '2026-09-13T03:00:00Z')
    updated = retain_margin_snapshot(corrected, path=path, raw=raw)
    assert updated['rows'][:len(original)] == original
    assert len(updated['rows']) == len(original) + 2
    assert all(r['revision'] == 1 for r in updated['rows'][len(original):])
    args = dict(instrument_id='1570', balance_kind='WEEKLY_MARGIN',
                long_series='margin.long_balance', short_series='margin.short_balance')
    before = credit_dynamics(updated['rows'], cutoff='2026-09-13T02:59:59Z', **args)
    after = credit_dynamics(updated['rows'], cutoff='2026-09-13T03:00:00Z', **args)
    assert before['current']['ratio'] == 10
    assert after['current']['ratio'] == 12
    restored = restore_margin_snapshot(path)
    assert restored['rows'] == updated['rows']
    assert restored['historyStatus'] == 'LOCAL_DURABLE'
    db = sqlite3.connect(path)
    assert db.execute('SELECT count(*) FROM raw_sources').fetchone()[0] == 2
    assert db.execute('SELECT count(*) FROM margin_input_history').fetchone()[0] == 6
    db.close()
    # Another identical fetch after restart appends neither observations nor revisions.
    again, raw = candidate([dict(rows[1], LongVol=180)], '2026-09-14T03:00:00Z')
    assert retain_margin_snapshot(again, path=path, raw=raw)['rows'] == updated['rows']


def test_margin_prefix_reuse_matches_full_features_after_received_correction(tmp_path):
    from jp_market_source_adapters import retain_margin_snapshot
    from jp_market_features import build_feature_history
    rows = [{'Date': '2026-08-28', 'Code': '15700', 'LongVol': 120, 'ShrtVol': 20},
            {'Date': '2026-09-04', 'Code': '15700', 'LongVol': 150, 'ShrtVol': 15}]
    def snapshot(values, at):
        return normalize({'data': values}, instrument_id='1570', observed_at=at,
                         response_sha256='a'*64, volume_unit='UNITS')
    first = retain_margin_snapshot(snapshot(rows, '2026-09-12T01:00:00Z'))
    cutoffs = ['2026-09-12T02:00:00Z', '2026-09-13T02:00:00Z']
    old = build_feature_history(price_series={}, cutoffs=cutoffs, margin_1570=first['rows'])
    old['status'] = 'AVAILABLE'  # The runtime admits and persists the completed history.
    repeat = retain_margin_snapshot(snapshot(rows, '2026-09-13T03:00:00Z'), previous=first)
    same = build_feature_history(price_series={}, cutoffs=cutoffs, margin_1570=repeat['rows'], previous_history=old)
    assert same['calculationWork']['evaluatedCutoffs'] == 0
    corrected = retain_margin_snapshot(snapshot([dict(rows[-1], LongVol=180)], '2026-09-14T01:00:00Z'), previous=repeat)
    expanded = cutoffs + ['2026-09-14T02:00:00Z']
    delta = build_feature_history(price_series={}, cutoffs=expanded, margin_1570=corrected['rows'], previous_history=old)
    full = build_feature_history(price_series={}, cutoffs=expanded, margin_1570=corrected['rows'])
    assert delta['calculationWork'] == {'evaluatedCutoffs': 1, 'reusedCutoffs': 2}
    for key in ('features', 'conditions', 'latest'):
        assert delta[key] == full[key]


def test_margin_durable_corruption_and_bad_raw_do_not_overwrite(tmp_path):
    import hashlib
    import json
    import sqlite3
    import pytest
    from jp_market_source_adapters import retain_margin_snapshot, restore_margin_snapshot
    raw = json.dumps({'data':[{'Date':'2026-09-04','Code':'15700','LongVol':150,'ShrtVol':15}]}).encode()
    candidate = normalize(json.loads(raw), instrument_id='1570', observed_at='2026-09-12T01:00:00Z',
                          response_sha256=hashlib.sha256(raw).hexdigest(), volume_unit='UNITS')
    path = tmp_path/'sources.sqlite3'
    retain_margin_snapshot(candidate, path=path, raw=raw)
    with pytest.raises(ValueError, match='raw_receipt'):
        retain_margin_snapshot(candidate, path=path, raw=b'wrong')
    assert restore_margin_snapshot(path)['rows'] == candidate['rows']
    db=sqlite3.connect(path); db.execute("UPDATE margin_input_history SET body='{}' WHERE seq=1"); db.commit(); db.close()
    with pytest.raises(ValueError, match='integrity'):
        restore_margin_snapshot(path)
    with pytest.raises(ValueError, match='integrity'):
        retain_margin_snapshot(candidate, path=path, raw=raw)
