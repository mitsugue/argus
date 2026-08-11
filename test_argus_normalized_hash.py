import copy
import math
import unicodedata
from datetime import date, datetime, timezone

import pytest

import argus_asset_chart_cache as assets
import argus_verified_snapshot as verified
from test_argus_asset_chart_cache import (
    ASSET_BOUNDARY_STATE_HASH,
    boundary_store as asset_boundary_store,
)
from test_argus_verified_snapshot import (
    VERIFIED_BOUNDARY_STATE_HASH,
    boundary_store as verified_boundary_store,
    candidate as verified_candidate,
)


def _events(module, value):
    rows = []
    digest = module.state_hash_normalized(
        value, diagnostic_observer=lambda phase, metadata: rows.append(
            (phase, metadata)))
    return digest, rows


def _verified_history_value(value):
    return {"history": [{"key": "compat", "value": value}]}


def _asset_record_value(value):
    return {
        "records": {"compat": {"publishedAt": "2026-08-11T00:00:00Z",
                               "value": value}},
        "current": {"JP:COMPAT:daily": "compat"},
    }


@pytest.mark.parametrize("module,raw", [
    (verified, _verified_history_value({
        "deep": [{"integer": 7, "float": 7.25, "none": None,
                  "tuple": ("x", 3.5), "list": [True, False, 0]}]})),
    (assets, _asset_record_value({
        "deep": [{"integer": 7, "float": 7.25, "none": None,
                  "tuple": ("x", 3.5), "list": [True, False, 0]}]})),
    (verified, _verified_history_value({"": "empty", "   ": "space"})),
    (assets, _asset_record_value({"": "empty", "   ": "space"})),
    (verified, _verified_history_value("日本株 🌐 𠀋")),
    (assets, _asset_record_value("日本株 🌐 𠀋")),
])
def test_supported_structural_and_unicode_matrix_matches_raw_truth(module, raw):
    original = copy.deepcopy(raw)
    normalized = module.normalize_store(raw)
    assert module.state_hash_normalized(normalized) == module.state_hash(raw)
    assert raw == original


@pytest.mark.parametrize("module,wrap", [
    (verified, _verified_history_value),
    (assets, _asset_record_value),
])
def test_unicode_nfc_and_nfd_remain_distinct_but_each_matches_raw(module, wrap):
    nfc = unicodedata.normalize("NFC", "Cafe\N{COMBINING ACUTE ACCENT}")
    nfd = unicodedata.normalize("NFD", "Caf\N{LATIN SMALL LETTER E WITH ACUTE}")
    assert nfc != nfd
    nfc_raw = wrap(nfc)
    nfd_raw = wrap(nfd)
    nfc_fast = module.state_hash_normalized(module.normalize_store(nfc_raw))
    nfd_fast = module.state_hash_normalized(module.normalize_store(nfd_raw))
    assert nfc_fast == module.state_hash(nfc_raw)
    assert nfd_fast == module.state_hash(nfd_raw)
    assert nfc_fast != nfd_fast


@pytest.mark.parametrize("module,wrap", [
    (verified, _verified_history_value),
    (assets, _asset_record_value),
])
def test_bool_and_int_remain_distinct_but_each_matches_raw(module, wrap):
    bool_raw = wrap(True)
    int_raw = wrap(1)
    bool_fast = module.state_hash_normalized(module.normalize_store(bool_raw))
    int_fast = module.state_hash_normalized(module.normalize_store(int_raw))
    assert bool_fast == module.state_hash(bool_raw)
    assert int_fast == module.state_hash(int_raw)
    assert bool_fast != int_fast


def test_negative_zero_preserves_each_modules_existing_numeric_contract():
    verified_negative = _verified_history_value(-0.0)
    verified_zero = _verified_history_value(0)
    verified_negative_fast = verified.state_hash_normalized(
        verified.normalize_store(verified_negative))
    assert verified_negative_fast == verified.state_hash(verified_negative)
    assert verified_negative_fast == verified.state_hash(verified_zero)

    asset_negative = _asset_record_value(-0.0)
    asset_zero = _asset_record_value(0)
    asset_negative_fast = assets.state_hash_normalized(
        assets.normalize_store(asset_negative))
    assert asset_negative_fast == assets.state_hash(asset_negative)
    assert asset_negative_fast != assets.state_hash(asset_zero)


@pytest.mark.parametrize("unsupported", [
    datetime(2026, 8, 11, 9, 7, tzinfo=timezone.utc),
    date(2026, 8, 11),
])
@pytest.mark.parametrize("module,wrap", [
    (verified, _verified_history_value),
    (assets, _asset_record_value),
])
def test_datetime_and_date_rejection_matches_raw_contract(
        module, wrap, unsupported):
    raw = wrap(unsupported)
    with pytest.raises(TypeError):
        module.state_hash(raw)
    with pytest.raises(TypeError):
        module.state_hash_normalized(module.normalize_store(raw))


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_non_finite_asymmetry_matches_each_existing_contract(non_finite):
    verified_raw = _verified_history_value(non_finite)
    with pytest.raises(ValueError):
        verified.state_hash(verified_raw)
    with pytest.raises(ValueError):
        verified.state_hash_normalized(verified.normalize_store(verified_raw))

    asset_raw = _asset_record_value(non_finite)
    assert assets.state_hash_normalized(
        assets.normalize_store(asset_raw)) == assets.state_hash(asset_raw)


@pytest.mark.parametrize("module,first,second", [
    (verified,
     _verified_history_value({"alpha": 1, "beta": 2}),
     _verified_history_value({"beta": 2, "alpha": 1})),
    (assets,
     _asset_record_value({"alpha": 1, "beta": 2}),
     _asset_record_value({"beta": 2, "alpha": 1})),
])
def test_alternate_mapping_insertion_order_is_canonical(module, first, second):
    first_fast = module.state_hash_normalized(module.normalize_store(first))
    second_fast = module.state_hash_normalized(module.normalize_store(second))
    assert first_fast == module.state_hash(first)
    assert second_fast == module.state_hash(second)
    assert first_fast == second_fast


@pytest.mark.parametrize("module,raw", [
    (verified, None),
    (verified, {"history": [{"label": "日本株 🌐", "value": 7.25}]}),
    (assets, None),
    (assets, {
        "records": {"unicode": {"name": "日本株 🌐", "value": 7.25}},
        "current": {"JP:TEST:daily": "unicode"},
        "cursor": "4",
    }),
])
def test_normalized_hash_compatibility_matrix_for_empty_unicode_and_float(
        module, raw):
    normalized = module.normalize_store(raw)
    original = copy.deepcopy(normalized)
    digest, rows = _events(module, normalized)
    assert digest == module.state_hash(raw)
    assert rows[0][0] == "hash_enter"
    assert rows[1][0] == "normalized_input_reused"
    assert all(phase != "normalized_input_fallback" for phase, _ in rows)
    assert normalized == original


def test_normalized_hash_boundary_digests_are_pinned():
    verified_normalized = verified.normalize_store(verified_boundary_store())
    asset_normalized = assets.normalize_store(asset_boundary_store())
    assert verified.state_hash_normalized(
        verified_normalized) == VERIFIED_BOUNDARY_STATE_HASH
    assert assets.state_hash_normalized(
        asset_normalized) == ASSET_BOUNDARY_STATE_HASH


def test_verified_integral_float_and_asset_json_number_semantics_are_unchanged():
    floating = verified_boundary_store()
    integral = copy.deepcopy(floating)
    for item in integral["current"].values():
        for bar in item["payload"]["indicators"]["bars"]:
            for field in ("open", "high", "low", "close"):
                bar[field] = int(bar[field])
    floating_normalized = verified.normalize_store(floating)
    integral_normalized = verified.normalize_store(integral)
    assert verified.state_hash_normalized(
        floating_normalized) == VERIFIED_BOUNDARY_STATE_HASH
    assert verified.state_hash_normalized(
        integral_normalized) == VERIFIED_BOUNDARY_STATE_HASH

    asset_float = assets.normalize_store({
        "records": {"r": {"value": 100.0}}, "current": {"i": "r"}})
    asset_int = assets.normalize_store({
        "records": {"r": {"value": 100}}, "current": {"i": "r"}})
    assert assets.state_hash_normalized(asset_float) == assets.state_hash(
        asset_float)
    assert assets.state_hash_normalized(asset_int) == assets.state_hash(
        asset_int)
    assert assets.state_hash_normalized(
        asset_float) != assets.state_hash_normalized(asset_int)


def test_nan_asymmetry_matches_each_existing_raw_contract():
    verified_raw = {"history": [{"value": math.nan}]}
    verified_normalized = verified.normalize_store(verified_raw)
    with pytest.raises(ValueError):
        verified.state_hash(verified_raw)
    with pytest.raises(ValueError):
        verified.state_hash_normalized(verified_normalized)

    asset_raw = {
        "records": {"r": {"value": math.nan}}, "current": {"i": "r"}}
    asset_normalized = assets.normalize_store(asset_raw)
    assert assets.state_hash_normalized(asset_normalized) == assets.state_hash(
        asset_raw)


def test_pruned_and_bounded_normalized_stores_match_raw_truth():
    verified_raw = {
        "history": [{"sequence": index}
                    for index in range(verified.MAX_HISTORY + 7)]}
    verified_normalized = verified.normalize_store(verified_raw)
    assert len(verified_normalized["history"]) == verified.MAX_HISTORY
    assert verified_normalized["history"][0]["sequence"] == 7
    assert verified.state_hash_normalized(
        verified_normalized) == verified.state_hash(verified_raw)

    asset_raw = {
        "records": {
            f"r-{index:02d}": {"publishedAt": f"2026-08-01T00:{index:02d}:00Z"}
            for index in range(assets.MAX_RECORDS + 7)
        },
        "current": {},
    }
    asset_normalized = assets.normalize_store(asset_raw)
    assert len(asset_normalized["records"]) == assets.MAX_RECORDS
    assert "r-00" not in asset_normalized["records"]
    assert "r-30" in asset_normalized["records"]
    assert assets.state_hash_normalized(
        asset_normalized) == assets.state_hash(asset_raw)


def test_verified_current_over_24_is_not_silently_redefined_by_hash_api():
    raw = verified_boundary_store()
    extra = verified_candidate(
        symbol="EXTRA", dataset_hash="data-extra",
        generated_at="2026-07-23T06:24:00Z")
    raw["current"][verified.snapshot_key(
        "market-chart", "EXTRA", "5D")] = extra
    normalized = verified.normalize_store(raw)
    assert len(normalized["current"]) == verified.MAX_CURRENT + 1
    assert verified.state_hash_normalized(
        normalized) == verified.state_hash(raw)


def test_verified_tampered_and_wrong_pointer_entries_are_dropped_identically():
    raw = verified_boundary_store()
    tampered = verified_candidate(
        symbol="TAMP", dataset_hash="data-tampered",
        generated_at="2026-07-23T06:24:00Z")
    tampered["payload"]["indicators"]["bars"][0]["close"] = 1.0
    raw["current"][verified.snapshot_key(
        "market-chart", "TAMP", "5D")] = tampered
    wrong_key_item = verified_candidate(
        symbol="WRONG", dataset_hash="data-wrong",
        generated_at="2026-07-23T06:25:00Z")
    raw["current"]["wrong:pointer:key"] = wrong_key_item
    normalized = verified.normalize_store(raw)
    assert len(normalized["current"]) == verified.MAX_CURRENT
    assert verified.state_hash_normalized(
        normalized) == verified.state_hash(raw)


def test_asset_protected_current_can_exceed_24_without_hash_contract_drift():
    raw = asset_boundary_store()
    raw["records"]["protected-extra"] = {
        "publishedAt": "2026-08-11T00:00:00Z", "value": 1}
    raw["current"]["JP:EXTRA:weekly"] = "protected-extra"
    normalized = assets.normalize_store(raw)
    assert len(normalized["records"]) == assets.MAX_RECORDS + 1
    assert len(normalized["current"]) == assets.MAX_RECORDS + 1
    assert assets.state_hash_normalized(
        normalized) == assets.state_hash(raw)


def test_asset_dangling_pointer_and_large_chart_history_match_raw_truth():
    raw = _asset_record_value({
        "bars": [{"date": f"2026-01-{(index % 28) + 1:02d}",
                  "close": 100 + index / 10}
                 for index in range(512)]})
    raw["current"]["JP:DANGLING:daily"] = "missing-record"
    normalized = assets.normalize_store(raw)
    assert "JP:DANGLING:daily" not in normalized["current"]
    assert len(normalized["records"]["compat"]["value"]["bars"]) == 512
    assert assets.state_hash_normalized(
        normalized) == assets.state_hash(raw)


def test_asset_cursor_and_last_updated_are_excluded_but_verified_time_is_not():
    asset_first = asset_boundary_store()
    asset_second = copy.deepcopy(asset_first)
    asset_second["cursor"] = 999
    asset_second["lastUpdatedAt"] = "2099-01-01T00:00:00Z"
    first_asset_hash = assets.state_hash_normalized(
        assets.normalize_store(asset_first))
    second_asset_hash = assets.state_hash_normalized(
        assets.normalize_store(asset_second))
    assert first_asset_hash == assets.state_hash(asset_first)
    assert second_asset_hash == assets.state_hash(asset_second)
    assert first_asset_hash == second_asset_hash

    verified_first = verified_boundary_store()
    verified_second = copy.deepcopy(verified_first)
    verified_second["lastPublishedAt"] = "2099-01-01T00:00:00Z"
    first_verified_hash = verified.state_hash_normalized(
        verified.normalize_store(verified_first))
    second_verified_hash = verified.state_hash_normalized(
        verified.normalize_store(verified_second))
    assert first_verified_hash == verified.state_hash(verified_first)
    assert second_verified_hash == verified.state_hash(verified_second)
    assert first_verified_hash != second_verified_hash


@pytest.mark.parametrize("copy_value", [
    lambda value: dict(value),
    lambda value: value.copy(),
    copy.copy,
    copy.deepcopy,
])
def test_copying_discards_normalized_provenance_and_falls_back(copy_value):
    for module, raw in (
            (verified, verified_boundary_store()),
            (assets, asset_boundary_store())):
        copied = copy_value(module.normalize_store(raw))
        digest, rows = _events(module, copied)
        assert digest == module.state_hash(copied)
        assert rows[0] == (
            "normalized_input_fallback", {"reason": "untrusted_provenance"})
        assert rows[1][0] == "hash_enter"
        assert rows[2][0] == "internal_normalize_complete"


def test_top_level_mutation_invalidates_provenance_without_changing_input_truth():
    for module, raw, key in (
            (verified, verified_boundary_store(), "lastPublishedAt"),
            (assets, asset_boundary_store(), "lastUpdatedAt")):
        normalized = module.normalize_store(raw)
        normalized[key] = normalized.get(key)
        original = copy.deepcopy(normalized)
        digest, rows = _events(module, normalized)
        assert digest == module.state_hash(normalized)
        assert rows[0][0] == "normalized_input_fallback"
        assert normalized == original


def test_cross_module_marker_is_rejected_in_constant_time_contract():
    verified_store = verified.normalize_store(verified_boundary_store())
    asset_store = assets.normalize_store(asset_boundary_store())
    verified_digest, verified_rows = _events(verified, asset_store)
    asset_digest, asset_rows = _events(assets, verified_store)
    assert verified_digest == verified.state_hash(asset_store)
    assert asset_digest == assets.state_hash(verified_store)
    assert verified_rows[0][0] == "normalized_input_fallback"
    assert asset_rows[0][0] == "normalized_input_fallback"


def test_observer_absence_constructs_no_diagnostic_metadata(monkeypatch):
    def forbidden_notify(*_args, **_kwargs):
        raise AssertionError("observer-free hashing must not notify")

    verified_store = verified.normalize_store(verified_boundary_store())
    asset_store = assets.normalize_store(asset_boundary_store())
    monkeypatch.setattr(verified, "_diagnostic_notify", forbidden_notify)
    monkeypatch.setattr(assets, "_diagnostic_notify", forbidden_notify)
    assert verified.state_hash_normalized(
        verified_store) == VERIFIED_BOUNDARY_STATE_HASH
    assert assets.state_hash_normalized(asset_store) == ASSET_BOUNDARY_STATE_HASH
