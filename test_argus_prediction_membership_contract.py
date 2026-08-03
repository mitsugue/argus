"""Prediction-ledger Layer 2B membership contract regressions."""
from __future__ import annotations

import json
import os
import sys
import types
from datetime import datetime
from unittest import mock

import argus_watchlist_sync as watchlist

_moomoo = types.ModuleType("moomoo")
_moomoo.OpenQuoteContext = lambda *args, **kwargs: None
_moomoo.OpenSecTradeContext = lambda *args, **kwargs: None
_moomoo.RET_OK = 0
sys.modules.setdefault("moomoo", _moomoo)
import scanner


def _snapshot(items):
    valid, cleaned, errors = watchlist.validate_sync_payload({"items": items})
    assert valid, errors
    return watchlist.build_membership_snapshot(
        cleaned["items"], effective_date="2026-08-03",
        generated_at="2026-08-03T07:00:00Z", snapshot_id="wl-contract")


def _private_result(snapshot=None, *, status="ok", revision="rev-1"):
    return {"status": status,
            "content": json.dumps(snapshot) if snapshot is not None else None,
            "revision": revision, "errorClass": None}


def _configured():
    return mock.patch.dict(os.environ, {
        "ARGUS_LAYER2B_PRIVATE_REPO": "owner/private",
        "ARGUS_LAYER2B_PRIVATE_TOKEN": "redacted-test-token",
    })


def test_never_synced_is_explicit_blocking_state():
    with _configured(), mock.patch.object(
            scanner, "_gh_private_get_detailed",
            return_value=_private_result(status="missing", revision=None)):
        result = scanner._layer2b_run()
    assert result == {
        "ok": False, "status": "blocked",
        "error": "membership_never_synced", "reason": "never_synced",
        "membershipState": "never_synced", "membershipCount": 0,
        "membershipVerified": False,
        "contractAction": "owner_watchlist_sync_required",
    }


def test_verified_zero_membership_is_expected_skip_not_failure():
    empty = _snapshot([])
    with _configured(), mock.patch.object(
            scanner, "_gh_private_get_detailed",
            return_value=_private_result(empty)):
        result = scanner._layer2b_run()
    assert result["ok"] is True
    assert result["status"] == "expected_skip"
    assert result["reason"] == "empty_by_design"
    assert result["membershipVerified"] is True
    assert result["membershipCount"] == 0


def test_invalid_membership_hash_blocks_without_exposing_symbols():
    invalid = _snapshot([{"symbol": "7203", "market": "JP"}])
    invalid["contentHash"] = "sha256:tampered"
    with _configured(), mock.patch.object(
            scanner, "_gh_private_get_detailed",
            return_value=_private_result(invalid)):
        result = scanner._layer2b_run()
    assert result["status"] == "blocked"
    assert result["error"] == "membership_contract_invalid"
    assert "7203" not in json.dumps(result)


def test_private_store_outage_is_not_misreported_as_never_synced():
    with _configured(), mock.patch.object(
            scanner, "_gh_private_get_detailed", return_value={
                "status": "unavailable", "content": None,
                "revision": None, "errorClass": "TimeoutError"}):
        result = scanner._layer2b_run()
    assert result["status"] == "blocked"
    assert result["membershipState"] == "membership_store_unavailable"
    assert result["error"] == "membership_store_unavailable"


def test_synced_membership_records_once_and_preserves_old_rows():
    current = _snapshot([{"symbol": "7203", "market": "JP"}])
    today = datetime.now(scanner.TZ_JST).strftime("%Y-%m-%d")
    old_row = {"id": "old-AAPL", "date": "2026-08-01",
               "symbol": "AAPL", "market": "US", "scored": {}}
    writes = {}

    def detailed(path):
        if path == "membership/latest.json":
            return _private_result(current)
        if path == "predictions.jsonl":
            return {"status": "ok", "content": json.dumps(old_row) + "\n",
                    "revision": "pred-rev", "errorClass": None}
        return _private_result(status="missing", revision=None)

    def put(path, content, message, overwrite=True):
        writes[path] = content
        return True

    with _configured(), \
            mock.patch.object(scanner, "_gh_private_get_detailed",
                              side_effect=detailed), \
            mock.patch.object(scanner, "_layer2b_live_prices",
                              return_value={"7203": (3000, 1.0, "JP")}), \
            mock.patch.object(scanner, "_gh_private_put", side_effect=put):
        first = scanner._layer2b_run()
        # Feed the first persisted rows back into a same-day duplicate run.
        persisted = writes["predictions.jsonl"]

        def duplicate_detailed(path):
            if path == "membership/latest.json":
                return _private_result(current)
            if path == "predictions.jsonl":
                return {"status": "ok", "content": persisted,
                        "revision": "pred-rev-2", "errorClass": None}
            return _private_result(status="missing", revision=None)

        with mock.patch.object(scanner, "_gh_private_get_detailed",
                               side_effect=duplicate_detailed):
            duplicate = scanner._layer2b_run()

    assert first["status"] == "success"
    assert first["recorded"] == 1
    assert first["membershipState"] == "synced"
    assert duplicate["recorded"] == 0
    rows = [json.loads(line) for line in persisted.splitlines()]
    assert old_row in rows
    assert any(row.get("date") == today and row.get("symbol") == "7203"
               for row in rows)


def test_workflow_runs_public_ledger_before_membership_enforcement():
    text = open(".github/workflows/prediction-ledger.yml", encoding="utf-8").read()
    commit_at = text.index("- name: Commit to ledger branch")
    enforce_at = text.index(
        "- name: Enforce Layer 2B membership contract after public ledger")
    assert commit_at < enforce_at
    assert "set +e" in text[text.index("id: layer2b"):commit_at]
    assert "steps.layer2b.outputs.contract == 'blocked'" in text
