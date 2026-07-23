import pathlib
import sys
import types
from unittest import mock

import pandas as pd

sys.modules.setdefault("moomoo", types.SimpleNamespace(
    OpenQuoteContext=object, OpenSecTradeContext=object, RET_OK=0))
import scanner


def test_jquants_index_audit_uses_official_v2_without_persisting_rows():
    class ClientV2:
        def __init__(self, api_key):
            assert api_key == "configured-secret"

        def get_idx_bars_daily(self, **kwargs):
            assert kwargs == {
                "from_yyyymmdd": mock.ANY,
                "to_yyyymmdd": mock.ANY,
            }
            return pd.DataFrame([
                {"Date": "2026-07-22", "Code": "0000", "O": 100,
                 "H": 102, "L": 99, "C": 101},
            ])

        def get_idx_bars_daily_topix(self, **kwargs):
            return pd.DataFrame([
                {"Date": "2026-07-22", "O": 3000, "H": 3010,
                 "L": 2990, "C": 3005},
            ])

    fake_module = types.SimpleNamespace(__version__="2.3.0", ClientV2=ClientV2)
    with mock.patch.object(scanner, "_JQUANTS_API_KEY", "configured-secret"), \
            mock.patch.dict(sys.modules, {"jquantsapi": fake_module}):
        result = scanner._jquants_index_audit()
    assert result["status"] == "success"
    assert result["providerConfigured"] is True
    assert result["credentialLengthPositive"] is True
    assert result["generic"]["ohlcFieldsPresent"] is True
    assert result["topix"]["latestDate"] == "2026-07-22"
    assert result["nikkeiIdentityStatus"] == "not_identifiable_from_response_schema"
    assert result["officialCloseComparison"] == "not_performed_identity_unverified"
    assert result["licenseAudit"]["decision"] == "keep_1321_etf_proxy"
    assert result["rawRowsPersisted"] is False
    assert "configured-secret" not in str(result)


def test_today_contract_keeps_one_probability_language_and_price_only_levels():
    panel = pathlib.Path(
        "web/src/components/today/ArgusTodayPanel.tsx").read_text()
    domain = pathlib.Path("web/src/domain/argusTodayView.ts").read_text()
    assert "5D 終値方向" in panel
    assert "directionProbabilities" in panel
    assert "levelProbabilities" not in panel
    assert "接触" not in panel
    assert "forecastId" in panel
    assert "signalEpisodeIds" in panel
    assert "supportResistanceIds" in panel
    assert "eventIds" in panel
    assert "an UP plurality can never create or promote a BUY" in domain


def test_1321_is_explicitly_an_etf_proxy_with_unverified_index_rights():
    source = pathlib.Path("scanner.py").read_text()
    route = pathlib.Path("web/src/routes/CommandCenter.tsx").read_text()
    assert '"proxyFor": "Nikkei 225" if symbol == "1321"' in source
    assert '"licenseStatus": "license_unverified" if symbol == "1321"' in source
    assert "日経225 ETF（1321）" in route
    assert "ETF PROXY" in pathlib.Path(
        "web/src/components/today/ArgusTodayPanel.tsx").read_text()
