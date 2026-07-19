import json
import os
import sys
import tempfile
import types
import unittest

import argus_decision_ledger as dl
import argus_remote_journal as rj

# moomoo package import writes a user-home log as a side effect. Replace only that
# external adapter in this unit process; scanner's real outcome function is used.
_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *a, **k: None
_moomoo.OpenSecTradeContext = lambda *a, **k: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


FC = {"id": "fc-test", "symbol": "9999", "market": "JP",
      "issuedAt": "2026-07-10T08:30:00+09:00",
      "forecastHorizon": "next_session", "origin": "forward_live",
      "integrityHash": "forecast-hash", "informationCutoffAt": "2026-07-10T08:30:00+09:00"}
T0 = "2026-07-11T16:00:00+09:00"
T1 = "2026-07-11T16:10:00+09:00"
T2 = "2026-07-11T16:31:00+09:00"


class OutcomeRetryTests(unittest.TestCase):
    def unresolved(self):
        out = dl.outcome_record(forecast=FC, outcome_as_of=T0,
                                start_price=None, end_price=None, now_iso=T0)
        return dl.schedule_outcome_retry(out, now_iso=T0,
                                         retry_interval_seconds=1800)

    def test_missing_price_is_unresolved_and_zero_not_scored(self):
        out = self.unresolved()
        self.assertEqual(out["resolutionState"], "unresolved_missing_price")
        self.assertNotIn("absoluteReturnPct", out)
        zero = dl.outcome_record(forecast=FC, outcome_as_of=T0,
                                 start_price=0, end_price=100, now_iso=T0)
        self.assertEqual(zero["status"], "unresolved")

    def test_before_interval_no_retry_and_same_tick_idempotent(self):
        out = self.unresolved()
        self.assertFalse(dl.outcome_retry_due(out, now_iso=T1))
        same = dl.retry_outcome_record(existing=out, forecast=FC,
                                       outcome_as_of=T1, start_price=None,
                                       end_price=None, now_iso=T1,
                                       retry_interval_seconds=1800)
        self.assertEqual(same, out)

    def test_after_interval_missing_increments_same_outcome(self):
        out = self.unresolved()
        retried = dl.retry_outcome_record(existing=out, forecast=FC,
                                          outcome_as_of=T2, start_price=None,
                                          end_price=None, now_iso=T2,
                                          retry_interval_seconds=1800)
        self.assertEqual(retried["id"], out["id"])
        self.assertEqual(retried["retryCount"], 1)
        self.assertEqual(retried["lastRetryAt"], T2)
        self.assertEqual(retried["resolutionState"], "retry_pending")

    def test_later_price_resolves_same_outcome_and_resolved_is_stable(self):
        out = self.unresolved()
        resolved = dl.retry_outcome_record(existing=out, forecast=FC,
                                            outcome_as_of=T2, start_price=100,
                                            end_price=105, now_iso=T2,
                                            retry_interval_seconds=1800)
        self.assertEqual(resolved["id"], out["id"])
        self.assertEqual(resolved["status"], "resolved")
        self.assertEqual(resolved["absoluteReturnPct"], 5.0)
        again = dl.retry_outcome_record(existing=resolved, forecast=FC,
                                        outcome_as_of="2026-07-12T16:00:00+09:00",
                                        start_price=100, end_price=1,
                                        now_iso="2026-07-12T16:00:00+09:00",
                                        retry_interval_seconds=1800)
        self.assertEqual(again, resolved)

    def test_restore_legacy_and_remote_readback(self):
        restored = json.loads(json.dumps(self.unresolved()))
        self.assertTrue(dl.outcome_retry_due(restored, now_iso=T2))
        legacy = {"forecastId": FC["id"], "status": "unresolved",
                  "immutableCreatedAt": T0}
        upgraded = dl.retry_outcome_record(existing=legacy, forecast=FC,
                                            outcome_as_of=T2, start_price=100,
                                            end_price=101, now_iso=T2,
                                            retry_interval_seconds=1800)
        self.assertEqual(upgraded["status"], "resolved")
        self.assertTrue(upgraded.get("id"))
        blob = {"schemaVersion": "argus-durable-v3", "generatedAt": T2,
                "outcomes": [upgraded]}
        receipt = rj.outcome_read_back_receipt(remote_blob=blob,
                                               local_outcomes=[upgraded],
                                               read_back_at=T2)
        self.assertEqual(receipt["verificationStatus"], "verified")
        self.assertEqual(receipt["ackedOutcomeIds"], [upgraded["id"]])
        corrupt = dict(upgraded, retryCount=999)
        receipt = rj.outcome_read_back_receipt(
            remote_blob={"outcomes": [corrupt]}, local_outcomes=[corrupt],
            read_back_at=T2)
        self.assertEqual(receipt["verificationStatus"], "no_match")

    def test_expiry_disabled_by_default_value(self):
        out = self.unresolved()
        retried = dl.retry_outcome_record(existing=out, forecast=FC,
                                          outcome_as_of="2027-07-11T16:00:00+09:00",
                                          start_price=None, end_price=None,
                                          now_iso="2027-07-11T16:00:00+09:00",
                                          retry_interval_seconds=1800,
                                          expire_after_seconds=0)
        self.assertNotEqual(retried["resolutionState"], "unresolved_expired")

    def test_restore_merge_never_rolls_resolved_back(self):
        resolved = dl.retry_outcome_record(
            existing=self.unresolved(), forecast=FC, outcome_as_of=T2,
            start_price=100, end_price=105, now_iso=T2,
            retry_interval_seconds=1800)
        stale = dict(self.unresolved(), retryCount=99,
                     lastRetryAt="2027-01-01T00:00:00+09:00")
        self.assertFalse(scanner._outcome_restore_is_newer(resolved, stale))
        self.assertTrue(scanner._outcome_restore_is_newer(stale, resolved))


class ScannerOutcomeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.old_price = getattr(scanner, "_price_history_cached", None)
        self.old_journal = scanner._journal
        self.old_interval = scanner._OUTCOME_RETRY_INTERVAL_SECONDS
        scanner._FORECAST_LEDGER.clear()
        scanner._OUTCOME_LEDGER.clear()
        scanner._journal = lambda *a, **k: None
        scanner._OUTCOME_RETRY_INTERVAL_SECONDS = 1800
        fc = dl.forecast_record(symbol="9999", market="JP",
                                issued_at="2026-07-10T08:30:00+09:00",
                                horizon="next_session",
                                target_type="catalyst_verdict",
                                forecast_value="unknown",
                                now_iso="2026-07-10T08:30:00+09:00")
        fc["origin"] = "forward_live"
        scanner._FORECAST_LEDGER.append(fc)

    def tearDown(self):
        scanner._FORECAST_LEDGER.clear()
        scanner._OUTCOME_LEDGER.clear()
        scanner._journal = self.old_journal
        scanner._OUTCOME_RETRY_INTERVAL_SECONDS = self.old_interval
        if self.old_price is None:
            delattr(scanner, "_price_history_cached")
        else:
            scanner._price_history_cached = self.old_price

    def test_real_resolver_retries_same_record_then_resolves(self):
        scanner._price_history_cached = lambda _s: []
        self.assertEqual(scanner._dl_resolve_matured(T0), 0)
        self.assertEqual(len(scanner._OUTCOME_LEDGER), 1)
        original_id = scanner._OUTCOME_LEDGER[0]["id"]
        scanner._dl_resolve_matured(T1)  # interval前
        self.assertEqual(scanner._OUTCOME_LEDGER[0]["retryCount"], 0)
        scanner._dl_resolve_matured(T2)  # interval後、まだ欠損
        self.assertEqual(len(scanner._OUTCOME_LEDGER), 1)
        self.assertEqual(scanner._OUTCOME_LEDGER[0]["id"], original_id)
        self.assertEqual(scanner._OUTCOME_LEDGER[0]["retryCount"], 1)
        scanner._price_history_cached = lambda _s: [
            {"date": "2026-07-10", "close": 100},
            {"date": "2026-07-11", "close": 105},
        ]
        t3 = "2026-07-11T17:02:00+09:00"
        self.assertEqual(scanner._dl_resolve_matured(t3), 1)
        self.assertEqual(len(scanner._OUTCOME_LEDGER), 1)
        self.assertEqual(scanner._OUTCOME_LEDGER[0]["id"], original_id)
        self.assertEqual(scanner._OUTCOME_LEDGER[0]["status"], "resolved")
        before = json.dumps(scanner._OUTCOME_LEDGER[0], sort_keys=True)
        scanner._price_history_cached = lambda _s: [
            {"date": "2026-07-10", "close": 100},
            {"date": "2026-07-11", "close": 1},
        ]
        scanner._dl_resolve_matured("2026-07-12T17:02:00+09:00")
        self.assertEqual(json.dumps(scanner._OUTCOME_LEDGER[0], sort_keys=True), before)

    def test_real_resolver_premature_and_legacy_safe(self):
        fc = scanner._FORECAST_LEDGER[0]
        fc["issuedAt"] = T0
        scanner._price_history_cached = lambda _s: []
        scanner._dl_resolve_matured(T0)
        self.assertEqual(scanner._OUTCOME_LEDGER, [])
        fc["issuedAt"] = "2026-07-10T08:30:00+09:00"
        scanner._OUTCOME_LEDGER.append({"forecastId": fc["id"],
                                        "status": "unresolved",
                                        "immutableCreatedAt": T0})
        scanner._price_history_cached = lambda _s: [
            {"date": "2026-07-10", "close": 100},
            {"date": "2026-07-11", "close": 101},
        ]
        scanner._dl_resolve_matured(T2)
        self.assertEqual(len(scanner._OUTCOME_LEDGER), 1)
        self.assertEqual(scanner._OUTCOME_LEDGER[0]["status"], "resolved")
        self.assertTrue(scanner._OUTCOME_LEDGER[0].get("id"))

    def test_local_persist_restore_retries_same_outcome(self):
        old_path = scanner._OSINT_PERSIST_FILE
        old_restored = scanner._OSINT_PERSIST_STATE.get("restored")
        old_durable = dict(scanner._DURABLE_STATE)
        try:
            with tempfile.TemporaryDirectory(prefix="argus-outcome-restore-") as td:
                scanner._OSINT_PERSIST_FILE = os.path.join(td, "durable.json")
                scanner._price_history_cached = lambda _s: []
                scanner._dl_resolve_matured(T0)
                original = dict(scanner._OUTCOME_LEDGER[0])
                scanner._osint_persist()

                scanner._OUTCOME_LEDGER.clear()
                scanner._OSINT_PERSIST_STATE["restored"] = False
                scanner._osint_restore_once()
                restored = scanner._OUTCOME_LEDGER[0]
                self.assertEqual(restored["id"], original["id"])
                self.assertEqual(restored["retryCount"], 0)
                self.assertEqual(restored["nextRetryAt"], original["nextRetryAt"])

                scanner._price_history_cached = lambda _s: [
                    {"date": "2026-07-10", "close": 100},
                    {"date": "2026-07-11", "close": 101},
                ]
                scanner._dl_resolve_matured(T2)
                self.assertEqual(scanner._OUTCOME_LEDGER[0]["id"], original["id"])
                self.assertEqual(scanner._OUTCOME_LEDGER[0]["status"], "resolved")
        finally:
            scanner._OSINT_PERSIST_FILE = old_path
            scanner._OSINT_PERSIST_STATE["restored"] = old_restored
            scanner._DURABLE_STATE.clear()
            scanner._DURABLE_STATE.update(old_durable)


if __name__ == "__main__":
    unittest.main()
