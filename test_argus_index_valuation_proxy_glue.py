"""The proxy lane reads the owner's weight file, calls J-Quants by date, and keeps
a bounded history, with no network when it is not configured.

The network is faked at requests.get; the weight table is a five-member
fixture with known factors, so the reconstructed PER can be checked exactly.
"""
import json
import os

import pytest

import argus_index_valuation_proxy as proxy_module
import scanner

CODES = ("1001", "1002", "1003", "1004", "1005")
FACTORS = {"1001": 1.0, "1002": 1.0, "1003": 1.0, "1004": 0.1, "1005": 0.5}
CLOSES = {"2026-08-31": {"1001": 1000.0, "1002": 2500.0, "1003": 800.0, "1004": 60000.0, "1005": 9000.0},
          "2026-09-01": {"1001": 1010.0, "1002": 2450.0, "1003": 810.0, "1004": 61000.0, "1005": 9100.0},
          "2026-09-02": {"1001": 1020.0, "1002": 2400.0, "1003": 790.0, "1004": 62000.0, "1005": 9200.0}}
FWD = {"1001": 50.0, "1002": 125.0, "1003": 40.0, "1004": 3000.0, "1005": 450.0}
DIVISOR = 25.0


def _index_close(day):
    return sum(CLOSES[day][c] * FACTORS[c] for c in CODES) / DIVISOR


def _weights_csv():
    total = sum(CLOSES["2026-08-31"][c] * FACTORS[c] for c in CODES)
    lines = [",".join(proxy_module.WEIGHT_COLUMNS)]
    for code in CODES:
        weight = CLOSES["2026-08-31"][code] * FACTORS[code] / total * 100
        lines.append(f'"2026/08/31","{code}","社名","業種","セクター","{weight:.4f}%"')
    lines.append('"本資料は日経の著作物であり、無断で複写、複製、転載または流布することができません。"')
    return ("\r\n".join(lines) + "\r\n").encode("cp932")


class _Response:
    def __init__(self, body):
        self.status_code = 200
        self._body = body

    def json(self):
        return self._body


def _fake_get(calls):
    def get(url, headers=None, params=None, timeout=None):
        calls.append(("bars" if url.endswith("/equities/bars/daily") else "valuation", dict(params or {})))
        assert headers == {"x-api-key": "test-key"}
        day = params["date"]
        if url.endswith("/equities/bars/daily"):
            rows = [{"Date": day, "Code": code + "0", "C": close} for code, close in CLOSES[day].items()]
        else:
            rows = [{"Date": day, "Code": code + "0", "FwdEPS": FWD[code], "EPS": FWD[code] * 0.9}
                    for code in CODES]
        return _Response({"data": rows})
    return get


@pytest.fixture()
def lane(tmp_path, monkeypatch):
    weight_path = tmp_path / "weights.csv"
    weight_path.write_bytes(_weights_csv())
    monkeypatch.setenv(scanner._NK225_WEIGHT_CSV_ENV, str(weight_path))
    monkeypatch.setattr(scanner, "_JQUANTS_API_KEY", "test-key")
    monkeypatch.setattr(scanner, "_DURABILITY_PATHS", {"root": str(tmp_path)})
    monkeypatch.setattr(scanner, "_cost_policy_durable_enabled", lambda: True)
    monkeypatch.setattr(proxy_module, "MINIMUM_PRICED_MEMBERS", 3)
    state = {"status": "NOT_RUN", "restoreAttempted": False, "weightsSha256": None, "weightsAsOf": None,
             "factors": None, "history": {}, "recommendedVariant": "FORECAST_SIGNED",
             "lastAttemptAt": None, "lastError": None, "lastErrorReason": None, "requestsLastWarm": 0}
    monkeypatch.setattr(scanner, "_JP_INDEX_PROXY", state)
    calls = []
    monkeypatch.setattr(scanner.requests, "get", _fake_get(calls))
    rows = [{"instrumentId": "NIKKEI_225_INDEX", "date": day, "close": _index_close(day)}
            for day in ("2026-09-01", "2026-09-02")]
    return {"state": state, "calls": calls, "rows": rows, "path": tmp_path / "jp_market_valuation_proxy.json"}


def test_the_lane_derives_factors_then_reconstructs_each_session(lane):
    scanner._jp_index_proxy_warm(lane["rows"])
    state = lane["state"]
    assert state["status"] == "AVAILABLE", state
    assert state["factors"]["factors"] == FACTORS
    assert sorted(state["history"]) == ["2026-09-01", "2026-09-02"]
    for day in ("2026-09-01", "2026-09-02"):
        price_sum = sum(CLOSES[day][c] * FACTORS[c] for c in CODES)
        eps_sum = sum(FWD[c] * FACTORS[c] for c in CODES)
        row = state["history"][day]
        assert abs(row["variants"]["FORECAST_SIGNED"]["per"] - price_sum / eps_sum) < 1e-9
        assert abs(row["impliedDivisor"] - DIVISOR) < 1e-6
        assert row["coverage"]["priced"] == 5 and "missingPriceCount" in row["coverage"]
        assert "missingPrice" not in row["coverage"]
    # one bars call for the weight date, then bars + valuation per session
    kinds = [kind for kind, _ in lane["calls"]]
    assert kinds.count("bars") == 3 and kinds.count("valuation") == 2
    saved = json.loads(lane["path"].read_text(encoding="utf-8"))
    assert saved["schemaVersion"] == proxy_module.SCHEMA and sorted(saved["history"]) == ["2026-09-01", "2026-09-02"]
    assert lane["path"].stat().st_mode & 0o777 == 0o600


def test_the_scale_row_and_the_public_view_never_carry_the_table(lane):
    scanner._jp_index_proxy_warm(lane["rows"])
    row = scanner._jp_index_proxy_row("2026-09-03T00:00:00Z")
    assert row["basis"] == proxy_module.PROXY_BASIS and row["date"] == "2026-09-02"
    assert abs(row["indexClose"] - _index_close("2026-09-02")) < 1e-9
    public = scanner._jp_index_proxy_public()
    assert public["status"] == "AVAILABLE" and public["weightsAsOf"] == "2026-08-31"
    assert public["factorCoverage"]["reducedFactorCount"] == 2
    assert [h["date"] for h in public["history"]] == ["2026-09-01", "2026-09-02"]
    text = json.dumps(public, ensure_ascii=False)
    for forbidden in ("weightPct", "1004\": 0.1", "weights.csv", "factors\": {"):
        assert forbidden not in text, forbidden


def test_a_second_warm_only_fills_new_sessions_and_a_new_table_resets(lane):
    scanner._jp_index_proxy_warm(lane["rows"])
    before = len(lane["calls"])
    scanner._jp_index_proxy_warm(lane["rows"])
    assert len(lane["calls"]) == before, "nothing new to fetch"
    # A different weight file means new factors and a fresh history.
    path = os.environ[scanner._NK225_WEIGHT_CSV_ENV]
    with open(path, "ab") as handle:
        handle.write(b"\r\n")
    scanner._jp_index_proxy_warm(lane["rows"])
    assert lane["state"]["factors"]["factors"] == FACTORS
    assert len(lane["calls"]) > before


def test_without_the_weight_file_nothing_is_fetched(lane, monkeypatch):
    monkeypatch.delenv(scanner._NK225_WEIGHT_CSV_ENV)
    scanner._jp_index_proxy_warm(lane["rows"])
    assert lane["state"]["status"] == "NOT_CONFIGURED"
    assert lane["calls"] == []
    assert scanner._jp_index_proxy_row("2026-09-03T00:00:00Z") is None


def test_code_keys_fold_the_check_digit_and_keep_alphanumerics():
    assert scanner._nk225_code_key("72030") == "7203"
    assert scanner._nk225_code_key("285A0") == "285A"
    assert scanner._nk225_code_key("7203") == "7203"
    assert scanner._nk225_code_key(" 543a ") == "543A"


def test_the_weight_file_is_found_by_path_by_name_or_by_default(lane, tmp_path, monkeypatch):
    """A dashboard value may be a name rather than a mounted path; the lane
    looks under the secret directory too, and with no variable tries Nikkei's
    own download name there. The status says which form was found."""
    secret_dir = tmp_path / "secrets"; secret_dir.mkdir()
    monkeypatch.setattr(scanner, "_NK225_SECRET_DIR", str(secret_dir))
    weight_path = os.environ[scanner._NK225_WEIGHT_CSV_ENV]
    # bare name → secret dir
    (secret_dir / "weights.csv").write_bytes(open(weight_path, "rb").read())
    monkeypatch.setenv(scanner._NK225_WEIGHT_CSV_ENV, "weights.csv")
    scanner._jp_index_proxy_warm(lane["rows"])
    assert lane["state"]["status"] == "AVAILABLE"
    assert lane["state"]["weightFileFound"] == "configured_name_in_secret_dir"
    # no variable → default name in secret dir
    (secret_dir / scanner._NK225_WEIGHT_DEFAULT_NAME).write_bytes(open(weight_path, "rb").read())
    monkeypatch.delenv(scanner._NK225_WEIGHT_CSV_ENV)
    lane["state"]["history"].clear()
    scanner._jp_index_proxy_warm(lane["rows"])
    assert lane["state"]["weightFileFound"] == "default_name_in_secret_dir"
    # a variable pointing nowhere, with no default, is still unreadable, not silent
    monkeypatch.setenv(scanner._NK225_WEIGHT_CSV_ENV, str(tmp_path / "missing.csv"))
    (secret_dir / scanner._NK225_WEIGHT_DEFAULT_NAME).unlink()
    scanner._jp_index_proxy_warm(lane["rows"])
    assert lane["state"]["status"] == "NOT_CONFIGURED"
    assert lane["state"]["lastErrorReason"] == "weight_file_unreadable"
    public = scanner._jp_index_proxy_public()
    assert "secrets" not in json.dumps(public) and "missing.csv" not in json.dumps(public)


def test_an_unreadable_table_yields_diagnostics_without_a_name(lane, tmp_path, monkeypatch):
    """When no candidate opens, the state says what kind of value was set and
    what the secret directory holds, in booleans and counts only."""
    secret_dir = tmp_path / "secrets"; secret_dir.mkdir()
    (secret_dir / "other-secret.pem").write_bytes(b"x")
    (secret_dir / "some_table.csv").write_bytes(b"y")
    monkeypatch.setattr(scanner, "_NK225_SECRET_DIR", str(secret_dir))
    monkeypatch.setenv(scanner._NK225_WEIGHT_CSV_ENV, "nikkei_weights.csv")
    monkeypatch.chdir(tmp_path)
    scanner._jp_index_proxy_warm(lane["rows"])
    state = lane["state"]
    assert state["status"] == "NOT_CONFIGURED" and state["lastErrorReason"] == "weight_file_unreadable"
    diag = state["weightFileDiagnostics"]
    assert diag == {"configured": True, "configuredIsAbsolute": False, "configuredContainsSeparator": False,
                    "configuredBasenameIsDefault": False, "configuredEndsWithCsv": True,
                    "secretDirExists": True, "secretDirFileCount": 2, "defaultNameInSecretDir": False,
                    "csvFilesInSecretDir": 1, "defaultNameInProjectRoot": False}
    text = json.dumps(scanner._jp_index_proxy_public(), ensure_ascii=False)
    for forbidden in ("other-secret", "some_table", "nikkei_weights", str(secret_dir)):
        assert forbidden not in text, forbidden
    # A table placed at the project root under the configured name is found.
    (tmp_path / "nikkei_weights.csv").write_bytes(_weights_csv())
    scanner._jp_index_proxy_warm(lane["rows"])
    assert state["weightFileFound"] in ("configured_path", "configured_name_in_project_root")
    assert state["weightFileDiagnostics"] is None
