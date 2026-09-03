from __future__ import annotations

import base64
from collections import deque
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

import argus_market_data_truth as truth
from argus_providers.tachibana.client import (
    READ_ONLY_COMPATIBLE_RESPONSE_IDS,
    READ_ONLY_COMPATIBLE_RESPONSE_LISTS,
    READ_ONLY_FUNCTIONS,
    READ_ONLY_RESPONSE_IDS,
    CircuitBreaker,
    ProviderReadDiagnostic,
    SlidingWindowLimiter,
    TachibanaReadOnlyClient,
)
from argus_providers.tachibana.config import TachibanaConfig
from argus_providers.tachibana.cross_validation import MismatchClass, compare_shadow
from argus_providers.tachibana.evidence import (
    build_live_pressure_evidence,
    register_shadow_adapter,
    to_canonical_observations,
)
from argus_providers.tachibana.event_stream import (
    EventLifecycleProgress,
    EventStatusTracker,
    EventTransportError,
    TachibanaEventLifecycle,
    WebSocketEventConnector,
)
from argus_providers.tachibana.models import (
    AuthDiagnostic,
    ErrorClass,
    Freshness,
    MarketStatus,
    ProviderHealth,
    SessionState,
    TachibanaError,
)
from argus_providers.tachibana.normalization import normalize_market_price
from argus_providers.tachibana.redaction import REDACTED, redact_structure, redact_text
from argus_providers.tachibana.sensor import (
    EventConnectionPolicy,
    EventReconnectBudget,
    EventSnapshotAssembler,
    EventSubscription,
    TransientLiveSensor,
    decode_event_base64_shift_jis,
    parse_event_frame,
)
from argus_providers.tachibana.session import RequestsJsonTransport, TachibanaSession
from argus_providers.tachibana.session_truth import (
    JapanCashPhase,
    parse_provider_datetime,
    resolve_jp_cash_session,
)
from argus_providers.tachibana.singleton import (
    ProcessSingletonLease,
    SingletonLeaseError,
)
from argus_providers.tachibana.runtime import (
    TachibanaLiveRuntime,
    cross_validate_current,
    validate_live_flags,
)
import argus_providers.tachibana.runtime as tachibana_runtime
from scripts.tachibana_readonly_smoke import (
    _observation_is_usable_and_fresh,
    _smoke_pass_allowed,
)
import scripts.tachibana_live_acceptance as live_acceptance
from scripts.tachibana_live_acceptance import _live_start_guard
from scripts.tachibana_live_sensor_service import (
    _consume_reauthentication_budget,
    _scheduled_sensor_start,
)


NOW = datetime(2026, 9, 1, 6, 0, 10, tzinfo=timezone.utc)


class MockTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post_json(self, url, payload, timeout):
        self.calls.append((url, dict(payload), timeout))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _write(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    os.chmod(path, 0o600)


def _virtual_urls() -> dict[str, str]:
    token = "QUJDREVGR0g="
    return {
        "sUrlRequest": f"https://kabuka.e-shiten.jp/e_api_v4r10/request/{token}/",
        "sUrlMaster": f"https://price-kabuka.e-shiten.jp/e_api_v4r10/master/{token}/",
        "sUrlPrice": f"https://price-kabuka.e-shiten.jp/e_api_v4r10/price/{token}/",
        "sUrlEvent": f"https://price-kabuka.e-shiten.jp/e_api_v4r10/event/{token}/",
        "sUrlEventWebSocket": (
            f"wss://price-kabuka.e-shiten.jp/e_api_v4r10/event_ws/{token}/"
        ),
    }


def _encrypted_session_response(
    public_key, *, url_overrides: dict[str, str] | None = None
) -> tuple[dict, dict[str, str]]:
    urls = _virtual_urls()
    urls.update(url_overrides or {})
    response = {
        "p_no": "1",
        "p_errno": "0",
        "sCLMID": "CLMAuthLoginAck",
        "sResultCode": "0",
        "sResultText": "",
    }
    for key, value in urls.items():
        response[key] = base64.b64encode(public_key.encrypt(
            value.encode("ascii"),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(), label=None,
            ),
        )).decode("ascii")
    return response, urls


def _session(tmp_path, responses, **overrides):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    auth_path = tmp_path / "auth-id"
    key_path = tmp_path / "private.pem"
    _write(auth_path, b"test-auth-id")
    _write(key_path, pem)
    config = TachibanaConfig(
        enabled=True, auth_id_path=auth_path, private_key_path=key_path,
        **overrides,
    )
    transport = MockTransport(responses)
    return TachibanaSession(config, transport, clock=lambda: NOW), transport, key


def _authenticated_session(tmp_path, read_responses=(), **overrides):
    session, transport, key = _session(tmp_path, [], **overrides)
    login, urls = _encrypted_session_response(key.public_key())
    transport.responses.extend([login, *read_responses])
    session.authenticate()
    return session, transport, urls


def _success(
    function_id: str,
    list_name: str | None = None,
    rows=None,
    *,
    p_no: str = "2",
) -> dict:
    response = {"p_no": p_no, "p_errno": "0", "sCLMID": function_id}
    if list_name is not None:
        response[list_name] = [] if rows is None else rows
    return response


def _row(**updates):
    row = {
        "sIssueCode": "6501", "pDPP": "2000", "pPRP": "1980",
        "pDYWP": "20", "pDYRP": "1.01", "pDOP": "1990",
        "pDHP": "2010", "pDLP": "1985", "pDV": "100000",
        "pDJ": "200000000", "pVWAP": "1998", "pQAP": "2001",
        "pQBP": "2000", "pAV": "900", "pBV": "1100",
        "tDPP:T": "15:00",
        "pGAP2": "2003", "pGAV2": "200", "pGAP1": "2001", "pGAV1": "100",
        "pGBP2": "1998", "pGBV2": "400", "pGBP1": "2000", "pGBV1": "300",
    }
    row.update(updates)
    return row


def _event_frame(
    sequence: int,
    command: str,
    *records: tuple[str, str],
    p_date: str = "2026.09.01-15:00:10.123",
) -> str:
    fields = [
        ("p_no", str(sequence)),
        ("p_date", p_date),
        ("p_cmd", command),
        *records,
    ]
    return "\x01".join(f"{key}\x02{value}" for key, value in fields) + "\x01"


def _ss_frame(
    sequence: int,
    event_number: int,
    *,
    provider_time: str = "20260901145959",
    login_permission: str = "1",
    system_status: str = "0",
    provider: str = "MSGSV",
    event_date: str = "2026.09.01-15:00:10.123",
) -> str:
    return _event_frame(
        sequence,
        "SS",
        ("p_PV", provider),
        ("p_ENO", str(event_number)),
        ("p_ALT", "0"),
        ("p_CT", provider_time),
        ("p_LK", login_permission),
        ("p_SS", system_status),
        p_date=event_date,
    )


def _us_frame(
    sequence: int,
    event_number: int,
    *,
    provider_time: str = "20260901150000",
    business_day: str = "0",
    operation_status: str = "200",
    market: str = "00",
    group_code: str = "",
    section: str = "",
    unit: str = "0101",
    category: str = "01",
    provider: str = "MSGSV",
    event_date: str = "2026.09.01-15:00:10.123",
) -> str:
    return _event_frame(
        sequence,
        "US",
        ("p_PV", provider),
        ("p_ENO", str(event_number)),
        ("p_ALT", "0"),
        ("p_CT", provider_time),
        ("p_MC", market),
        ("p_GSCD", group_code),
        ("p_SHSB", section),
        ("p_UC", category),
        ("p_UU", unit),
        ("p_EDK", business_day),
        ("p_US", operation_status),
        p_date=event_date,
    )


class FakeWebSocketConnection:
    def __init__(self, messages):
        self.messages = list(messages)
        self.closed = False
        self.receive_timeouts = []

    def recv(self, timeout=None):
        self.receive_timeouts.append(timeout)
        if not self.messages:
            raise RuntimeError("connection closed")
        value = self.messages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


class ScriptedEventConnector:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.calls = []

    def receive(self, endpoint, subscription, **kwargs):
        self.calls.append((endpoint, subscription, kwargs))
        script = self.scripts.pop(0)
        if callable(script):
            return script(kwargs["stop_event"])
        return iter(script)


def test_phase_one_config_is_disabled_shadow_expands_paths_and_bounds_websocket():
    config = TachibanaConfig()
    assert config.enabled is False
    assert config.shadow_only is True
    assert config.authoritative is False
    assert config.websocket_enabled is False
    assert config.auth_id_path.is_absolute()
    with pytest.raises(ValueError, match="authority"):
        TachibanaConfig(authoritative=True)
    with pytest.raises(ValueError, match="shadow"):
        TachibanaConfig(shadow_only=False)
    with pytest.raises(ValueError, match="bounds"):
        TachibanaConfig(max_event_reconnects_per_day=11)


def test_auth_uses_official_ack_oaep_sha256_and_category_urls(tmp_path):
    session, transport, key = _session(tmp_path, [])
    response, urls = _encrypted_session_response(key.public_key())
    transport.responses.append(response)
    session.authenticate()
    assert session.state == SessionState.AVAILABLE
    called_url, payload, _ = transport.calls[0]
    assert called_url == "https://kabuka.e-shiten.jp/e_api_v4r10/auth/"
    assert payload["sCLMID"] == "CLMAuthLoginRequest"
    assert payload["sAuthId"] == "test-auth-id"
    assert payload["p_no"] == "1"
    assert payload["p_sd_date"] == "2026.09.01-15:00:10.000"
    assert payload["sJsonOfmt"] == "5"
    assert repr(session._endpoints) == "VirtualEndpoints(<redacted>)"
    assert session._market_data_endpoint("price") == urls["sUrlPrice"]
    assert not hasattr(session, "endpoint")


@pytest.mark.parametrize("mutation", [
    {"sCLMID": "CLMAuthLoginRequest"},
    {"p_no": "2"},
    {"p_errno": None},
])
def test_auth_response_shape_fails_closed(tmp_path, mutation):
    session, transport, key = _session(tmp_path, [])
    response, _ = _encrypted_session_response(key.public_key())
    response.update(mutation)
    transport.responses.append(response)
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert caught.value.classification == ErrorClass.AUTH_PROTOCOL_FAILED
    assert session.auth_diagnostic.boundary == "PROTOCOL_FAILED"
    assert session.state == SessionState.AUTH_FAILED
    assert session._endpoints is None


@pytest.mark.parametrize("response, expected", [
    ({"p_no": "1", "p_errno": "-62", "sCLMID": "CLMAuthLoginRequest"},
     ErrorClass.OUTSIDE_HOURS),
    ({"p_no": "1", "p_errno": "9", "sCLMID": "CLMAuthLoginRequest"},
     ErrorClass.AUTH_MAINTENANCE),
    ({"p_no": "1", "p_errno": "-2", "sCLMID": "CLMAuthLoginRequest"},
     ErrorClass.RATE_LIMITED),
])
def test_auth_error_envelope_is_classified_before_success_only_fields(
    tmp_path, response, expected
):
    session, transport, _ = _session(tmp_path, [response])
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert caught.value.classification == expected
    assert session._endpoints is None


@pytest.mark.parametrize(("result", "expected", "normalized", "reason"), [
    (
        "123456", ErrorClass.AUTH_SERVER_REJECTED,
        "AUTH_SERVER_REJECTED_123456", "UNMAPPED_OFFICIAL_RESULT_CODE",
    ),
    (
        "990002", ErrorClass.AUTH_MAINTENANCE,
        "AUTH_MAINTENANCE", "SYSTEM_TEMPORARILY_STOPPED",
    ),
    (
        "10005", ErrorClass.AUTH_IP_REJECTED,
        "AUTH_IP_REJECTED", "IP_ADDRESS_INVALID",
    ),
    (
        "10033", ErrorClass.AUTH_LOCKED,
        "AUTH_LOCKED", "USER_MANAGEMENT_LOGIN_LOCKED",
    ),
])
def test_auth_server_rejection_retains_only_safe_official_diagnostics(
    tmp_path, result, expected, normalized, reason,
):
    response = {
        "p_no": "1", "p_errno": "0", "sCLMID": "CLMAuthLoginAck",
        "sResultCode": result, "sResultText": "must not be retained",
    }
    session, transport, _ = _session(tmp_path, [response])
    transport.last_http_status = 200
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert caught.value.classification == expected
    assert session.auth_diagnostic.safe_dict() == {
        "classification": normalized,
        "boundary": "SERVER_AUTH_REJECTED",
        "httpStatus": 200,
        "sCLMID": "CLMAuthLoginAck",
        "sResultCode": result,
        "officialReason": reason,
        "responseMatchedCLMAuthLoginAck": True,
        "encryptedVirtualUrlsPresent": False,
    }
    assert "must not be retained" not in repr(session.auth_diagnostic)


def test_auth_diagnostic_rejects_unbounded_or_secret_shaped_fields():
    with pytest.raises(ValueError, match="invalid_auth_diagnostic"):
        AuthDiagnostic(classification="owner-auth-secret")
    with pytest.raises(ValueError, match="invalid_auth_diagnostic"):
        AuthDiagnostic(result_code="not-a-result-code")
    with pytest.raises(ValueError, match="invalid_auth_diagnostic"):
        AuthDiagnostic(http_status=999)


def test_auth_success_without_virtual_urls_is_not_server_rejection(tmp_path):
    response = {
        "p_no": "1", "p_errno": "0", "sCLMID": "CLMAuthLoginAck",
        "sResultCode": "0", "sKinsyouhouMidokuFlg": "1",
    }
    session, _, _ = _session(tmp_path, [response])
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert (
        caught.value.classification
        == ErrorClass.AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD
    )
    assert (
        session.auth_diagnostic.classification
        == "AUTH_SUCCESS_VIRTUAL_URLS_WITHHELD"
    )
    assert session.auth_diagnostic.result_code == "0"
    assert session.auth_diagnostic.encrypted_virtual_urls_present is False
    assert session.state == SessionState.UNAVAILABLE


def test_auth_success_decryption_failure_has_its_own_boundary(tmp_path):
    session, transport, key = _session(tmp_path, [])
    response, _ = _encrypted_session_response(key.public_key())
    response["sUrlPrice"] = "not-valid-base64"
    transport.responses.append(response)
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert caught.value.classification == ErrorClass.AUTH_SUCCESS_DECRYPT_FAILED
    assert session.auth_diagnostic.classification == "AUTH_SUCCESS_DECRYPT_FAILED"
    assert session.auth_diagnostic.boundary == "DECRYPT_FAILED"
    assert session.auth_diagnostic.result_code == "0"
    assert session.auth_diagnostic.encrypted_virtual_urls_present is True


def test_auth_id_bom_and_edge_whitespace_are_removed_before_json(tmp_path):
    session, transport, key = _session(tmp_path, [])
    _write(
        session.config.auth_id_path,
        b"\xef\xbb\xbf\r\n  test-auth-id  \r\n",
    )
    response, _ = _encrypted_session_response(key.public_key())
    transport.responses.append(response)
    session.authenticate()
    called_url, payload, _ = transport.calls[0]
    assert called_url == "https://kabuka.e-shiten.jp/e_api_v4r10/auth/"
    assert payload["sAuthId"] == "test-auth-id"
    assert str(session.config.auth_id_path) not in payload.values()


def test_auth_and_logout_accept_officially_optional_result_code(tmp_path):
    session, transport, key = _session(tmp_path, [])
    response, _ = _encrypted_session_response(key.public_key())
    response.pop("sResultCode")
    transport.responses.extend([
        response,
        {"p_no": "2", "p_errno": "0", "sCLMID": "CLMAuthLogoutAck"},
    ])
    session.authenticate()
    assert session.state == SessionState.AVAILABLE
    assert session.logout() is True
    assert session._endpoints is None


def test_auth_rejects_wrong_category_or_version_in_decrypted_url(tmp_path):
    session, transport, key = _session(tmp_path, [])
    response, _ = _encrypted_session_response(key.public_key(), url_overrides={
        "sUrlMaster": (
            "https://price-kabuka.e-shiten.jp/e_api_v4r9/price/QUJDREVGR0g=/"
        ),
    })
    transport.responses.append(response)
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert caught.value.classification == ErrorClass.AUTH_PROTOCOL_FAILED
    assert session.auth_diagnostic.boundary == "PROTOCOL_FAILED"


def test_auth_has_no_retry_and_secret_permissions_fail_closed(tmp_path):
    auth_path, key_path = tmp_path / "auth", tmp_path / "key.pem"
    _write(auth_path, b"secret-id")
    _write(key_path, b"not a key")
    transport = MockTransport([])
    session = TachibanaSession(TachibanaConfig(
        enabled=True, auth_id_path=auth_path, private_key_path=key_path,
    ), transport)
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert str(caught.value) == "PRIVATE_KEY_INVALID"
    assert transport.calls == []
    os.chmod(auth_path, 0o644)
    with pytest.raises(TachibanaError) as caught:
        session.authenticate()
    assert caught.value.classification == ErrorClass.SECRET_PERMISSIONS


def test_production_loader_accepts_pkcs8_rsa_pem_without_network(tmp_path):
    session, transport, key = _session(tmp_path, [])
    response, _ = _encrypted_session_response(key.public_key())
    transport.responses.append(response)
    session.authenticate()
    assert session.state == SessionState.AVAILABLE
    assert len(transport.calls) == 1
    session.expire()
    assert session.state == SessionState.EXPIRED


def test_authentication_is_serialized_with_reads(tmp_path):
    session, transport, key = _session(tmp_path, [])
    response, _ = _encrypted_session_response(key.public_key())
    transport.responses.append(response)
    started = threading.Event()
    completed = threading.Event()

    def worker():
        started.set()
        session.authenticate()
        completed.set()

    session.request_lock.acquire()
    thread = threading.Thread(target=worker)
    thread.start()
    assert started.wait(1)
    assert not completed.wait(0.05)
    assert transport.calls == []
    session.request_lock.release()
    thread.join(2)
    assert completed.is_set()


def test_logout_requires_official_ack_and_always_erases_urls(tmp_path):
    ack = {
        "p_no": "2", "p_errno": "0", "sCLMID": "CLMAuthLogoutAck",
        "sResultCode": "0",
    }
    session, transport, urls = _authenticated_session(tmp_path, [ack])
    assert session.logout() is True
    assert transport.calls[-1][0] == urls["sUrlRequest"]
    assert transport.calls[-1][1]["sCLMID"] == "CLMAuthLogoutRequest"
    assert transport.calls[-1][1]["p_no"] == "2"
    assert session.state == SessionState.EXPIRED
    assert session._endpoints is None


def test_logout_missing_protocol_errno_is_not_success(tmp_path):
    session, _, _ = _authenticated_session(tmp_path, [{
        "p_no": "2", "sCLMID": "CLMAuthLogoutAck", "sResultCode": "0",
    }])
    assert session.logout() is False
    assert session._endpoints is None


def test_allowlist_is_exact_immutable_and_there_is_no_generic_dispatch(tmp_path):
    assert dict(READ_ONLY_FUNCTIONS) == {
        "CLMMfdsGetMarketPrice": "PRICE",
        "CLMMfdsGetMarketPriceHistory": "PRICE",
        "CLMMfdsGetIssueDetail": "MASTER",
        "CLMMfdsGetSyoukinZan": "MASTER",
        "CLMMfdsGetShinyouZan": "MASTER",
        "CLMMfdsGetHibuInfo": "MASTER",
        "CLMStkGetIssueMstKabu": "MASTER",
        "CLMStkGetDateZyouhou": "MASTER",
    }
    with pytest.raises(TypeError):
        READ_ONLY_FUNCTIONS["CLMKabuNewOrder"] = "REQUEST"
    assert dict(READ_ONLY_RESPONSE_IDS) == {
        "CLMMfdsGetMarketPrice": "CLMMfdsGetMarketPrice",
        "CLMMfdsGetMarketPriceHistory": "CLMMfdsGetMarketPriceHistory",
        "CLMMfdsGetIssueDetail": "CLMMfdsGetIssueDetail",
        "CLMMfdsGetSyoukinZan": "CLMMfdsGetSyoukinZan",
        "CLMMfdsGetShinyouZan": "CLMMfdsGetShinyouZan",
        "CLMMfdsGetHibuInfo": "CLMMfdsGetHibuInfo",
        "CLMStkGetIssueMstKabu": "CLMStkGetIssueMstKabu",
        "CLMStkGetDateZyouhou": "CLMDateZyouhou",
    }
    with pytest.raises(TypeError):
        READ_ONLY_RESPONSE_IDS["CLMStkGetDateZyouhou"] = (
            "CLMStkGetDateZyouhou"
        )
    assert dict(READ_ONLY_COMPATIBLE_RESPONSE_IDS) == {
        "CLMStkGetDateZyouhou": frozenset({"CLMStkGetDateZyouhou"}),
    }
    with pytest.raises(TypeError):
        READ_ONLY_COMPATIBLE_RESPONSE_IDS["CLMMfdsGetMarketPrice"] = (
            frozenset({"CLMUnknownPriceResponse"})
        )
    assert dict(READ_ONLY_COMPATIBLE_RESPONSE_LISTS) == {
        "CLMStkGetDateZyouhou": frozenset({"aCLMStkDateZyouhou"}),
    }
    with pytest.raises(TypeError):
        READ_ONLY_COMPATIBLE_RESPONSE_LISTS["CLMMfdsGetMarketPrice"] = (
            frozenset({"aCLMUnknownPriceList"})
        )
    session, transport, _ = _session(tmp_path, [])
    client = TachibanaReadOnlyClient(session)
    assert not hasattr(client, "read")
    assert not hasattr(client, "request")
    with pytest.raises(TachibanaError) as caught:
        client.market_price(("6501",), ("sSecondPassword",))
    assert caught.value.classification == ErrorClass.CONFIGURATION
    assert transport.calls == []


def test_typed_routes_protocol_fields_and_alpha_symbols(tmp_path):
    result = _success("CLMMfdsGetMarketPrice", "aCLMMfdsMarketPrice", [{
        "sIssueCode": "130A", "pDPP": "1000",
    }])
    session, transport, urls = _authenticated_session(tmp_path, [result])
    client = TachibanaReadOnlyClient(session)
    response = client.market_price(("130A",), ("pDPP", "tDPP:T"))
    assert response["aCLMMfdsMarketPrice"][0]["sIssueCode"] == "130A"
    url, payload, _ = transport.calls[-1]
    assert url == urls["sUrlPrice"]
    assert payload == {
        "sTargetIssueCode": "130A",
        "sTargetColumn": "pDPP,tDPP:T",
        "p_no": "2",
        "p_sd_date": "2026.09.01-15:00:10.000",
        "sJsonOfmt": "5",
        "sCLMID": "CLMMfdsGetMarketPrice",
    }
    with pytest.raises(TachibanaError):
        client.market_price(("AAAA",), ("pDPP",))


def test_issue_and_balance_inquiries_route_to_master_and_history_to_price(tmp_path):
    calls = [
        ("CLMMfdsGetIssueDetail", "aCLMMfdsIssueDetail"),
        ("CLMMfdsGetSyoukinZan", "aCLMMfdsSyoukinZan"),
        ("CLMMfdsGetShinyouZan", "aCLMMfdsShinyouZan"),
        ("CLMMfdsGetHibuInfo", "aCLMMfdsHibuInfo"),
        ("CLMStkGetIssueMstKabu", "aCLMStkIssueMstKabu"),
        ("CLMMfdsGetMarketPriceHistory", "aCLMMfdsMarketPriceHistory"),
    ]
    responses = [
        _success(function_id, list_name, p_no=str(sequence))
        for sequence, (function_id, list_name) in enumerate(calls, start=2)
    ]
    session, transport, urls = _authenticated_session(tmp_path, responses)
    client = TachibanaReadOnlyClient(session)
    client.issue_detail(("6501",))
    client.securities_finance_balance(("6501",))
    client.margin_balance(("6501",))
    client.reverse_day_interest(("6501",))
    client.stock_issue_master()
    client.market_price_history("6501")
    routed = [call[0] for call in transport.calls[1:]]
    assert routed[:5] == [urls["sUrlMaster"]] * 5
    assert routed[5] == urls["sUrlPrice"]


def test_price_response_clmid_remains_exact_after_date_exception(tmp_path):
    response = _success(
        "CLMUnknownPriceResponse", "aCLMMfdsMarketPrice",
        [{"sIssueCode": "6501", "pDPP": "2000"}],
    )
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError):
        client.market_price(("6501",), ("pDPP",))
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == "PRICE_BASELINE_RESPONSE_CLMID"
    assert diagnostic["expectedResponseCLMID"] == "CLMMfdsGetMarketPrice"
    assert diagnostic["observedResponseCLMID"] == "CLMUnknownPriceResponse"


def test_other_master_response_clmid_remains_exact_after_date_exception(tmp_path):
    response = _success("CLMUnknownMasterResponse", "aCLMMfdsIssueDetail")
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError):
        client.issue_detail(("6501",))
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == "PROVIDER_READ_RESPONSE_CLMID"
    assert diagnostic["expectedResponseCLMID"] == "CLMMfdsGetIssueDetail"
    assert diagnostic["observedResponseCLMID"] == "CLMUnknownMasterResponse"


def test_official_date_information_uses_day_key_001_on_master(tmp_path):
    response = {
        "p_no": "2",
        "p_errno": "0",
        "sCLMID": "CLMDateZyouhou",
        "aCLMDateZyouhou": [{
            "sDayKey": "001",
            "sTheDay": "20260902",
            "sMaeEigyouDay_1": "20260901",
            "sYokuEigyouDay_1": "20260903",
        }, {
            "sDayKey": "002",
            "sTheDay": "20260903",
        }],
    }
    session, transport, urls = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    assert client.provider_calendar_date() == date(2026, 9, 2)
    url, payload, _timeout = transport.calls[-1]
    assert url == urls["sUrlMaster"]
    assert payload["sCLMID"] == "CLMStkGetDateZyouhou"
    assert payload["p_no"] == "2"
    assert client.read_diagnostic_safe_dict() == {
        "operation": "CLMStkGetDateZyouhou",
        "endpointClass": "MASTER",
        "stage": "PROVIDER_DATE_VALUE",
        "classification": "PASS",
        "httpStatus": None,
        "expectedResponseCLMID": "CLMDateZyouhou",
        "observedResponseCLMID": "CLMDateZyouhou",
        "responseCLMIDMode": "DOCUMENTED",
        "responseListMode": "DOCUMENTED",
        "resultCode": None,
        "schemaFailureToken": None,
        "unexpectedTopLevelFields": [],
    }


def test_live_observed_date_response_echo_uses_narrow_compatibility(tmp_path):
    # Exact production shape observed live on 2026-09-03 10:46 JST (bounded
    # names-only diagnostic): both the sCLMID and the row-list key echo the
    # request identifier.
    response = {
        "p_no": "2", "p_errno": "0",
        "sCLMID": "CLMStkGetDateZyouhou",
        "aCLMStkDateZyouhou": [{
            "sDayKey": "001", "sTheDay": "20260902",
        }],
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    assert client.provider_calendar_date() == date(2026, 9, 2)
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == "PROVIDER_DATE_VALUE"
    assert diagnostic["classification"] == "PASS"
    assert diagnostic["observedResponseCLMID"] == "CLMStkGetDateZyouhou"
    assert diagnostic["responseCLMIDMode"] == "PRODUCTION_ECHO_COMPAT"
    assert diagnostic["responseListMode"] == "PRODUCTION_ECHO_COMPAT"
    assert diagnostic["unexpectedTopLevelFields"] == []
    # provider_calendar_date reads only the documented key, so a PASS here
    # proves the echo list key was normalized before the consumer saw it.


def test_date_echo_clmid_with_documented_list_key_is_still_accepted(tmp_path):
    response = {
        "p_no": "2", "p_errno": "0",
        "sCLMID": "CLMStkGetDateZyouhou",
        "aCLMDateZyouhou": [{
            "sDayKey": "001", "sTheDay": "20260902",
        }],
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    assert client.provider_calendar_date() == date(2026, 9, 2)
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["responseCLMIDMode"] == "PRODUCTION_ECHO_COMPAT"
    assert diagnostic["responseListMode"] == "DOCUMENTED"


@pytest.mark.parametrize("response", [
    # Documented sCLMID with the echo list key: not a live-proven shape.
    {"p_no": "2", "p_errno": "0", "sCLMID": "CLMDateZyouhou",
     "aCLMStkDateZyouhou": [{"sDayKey": "001", "sTheDay": "20260902"}]},
    # Both list keys at once: ambiguous.
    {"p_no": "2", "p_errno": "0", "sCLMID": "CLMStkGetDateZyouhou",
     "aCLMDateZyouhou": [{"sDayKey": "001", "sTheDay": "20260902"}],
     "aCLMStkDateZyouhou": [{"sDayKey": "001", "sTheDay": "20260903"}]},
])
def test_date_list_key_shapes_outside_live_proof_fail_closed(tmp_path, response):
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError) as caught:
        client.provider_calendar_date()
    assert caught.value.classification == ErrorClass.PROVIDER
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == "PROVIDER_DATE_SCHEMA"
    assert diagnostic["schemaFailureToken"] == "RESPONSE_LIST_SHAPE_INVALID"
    assert diagnostic["responseListMode"] is None


def test_echo_list_key_is_date_only_and_unknown_for_price(tmp_path):
    response = {
        "p_no": "2", "p_errno": "0", "sCLMID": "CLMMfdsGetMarketPrice",
        "aCLMMfdsMarketPrice": [{"sIssueCode": "6501", "pDPP": "100"}],
        "aCLMStkDateZyouhou": [],
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError) as caught:
        client.market_price(("6501",), ("pDPP",))
    assert caught.value.classification == ErrorClass.PROVIDER
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["schemaFailureToken"] == "TOP_LEVEL_FIELD_UNKNOWN"
    assert diagnostic["unexpectedTopLevelFields"] == ["aCLMStkDateZyouhou"]


def test_date_response_third_clmid_still_fails_closed(tmp_path):
    response = {
        "p_no": "2", "p_errno": "0",
        "sCLMID": "CLMUnknownDateResponse",
        "aCLMDateZyouhou": [{
            "sDayKey": "001", "sTheDay": "20260902",
        }],
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError) as caught:
        client.provider_calendar_date()
    assert caught.value.classification == ErrorClass.PROVIDER
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == "PROVIDER_DATE_RESPONSE_CLMID"
    assert diagnostic["expectedResponseCLMID"] == "CLMDateZyouhou"
    assert diagnostic["observedResponseCLMID"] == "CLMUnknownDateResponse"
    assert diagnostic["responseCLMIDMode"] is None
    assert diagnostic["schemaFailureToken"] == "CLMID_MISMATCH"


@pytest.mark.parametrize(("response_update", "stage", "token"), [
    ({}, "PROVIDER_DATE_SCHEMA", "DATE_LIST_MISSING"),
    ({"aCLMDateZyouhou": []},
     "PROVIDER_DATE_DAYKEY", "DAYKEY_001_MISSING"),
    ({"aCLMDateZyouhou": [{
        "sDayKey": "002", "sTheDay": "20260903",
    }]}, "PROVIDER_DATE_DAYKEY", "DAYKEY_001_MISSING"),
    ({"aCLMDateZyouhou": [
        {"sDayKey": "001", "sTheDay": "20260902"},
        {"sDayKey": "001", "sTheDay": "20260902"},
    ]}, "PROVIDER_DATE_DAYKEY", "DAYKEY_001_DUPLICATE"),
    ({"aCLMDateZyouhou": [
        {"sDayKey": "001", "sTheDay": "20260902"},
        {"sDayKey": "001", "sTheDay": "20260903"},
    ]}, "PROVIDER_DATE_DAYKEY", "DAYKEY_001_CONFLICT"),
    ({"aCLMDateZyouhou": [{
        "sDayKey": "001", "sTheDay": "20260230",
    }]}, "PROVIDER_DATE_VALUE", "CURRENT_DATE_INVALID"),
    ({"aCLMDateZyouhou": [{
        "sDayKey": "001", "sTheDay": "2026-09-02",
    }]}, "PROVIDER_DATE_SCHEMA", "DATE_ROW_INVALID"),
])
def test_date_official_and_adversarial_fixtures_are_stage_classified(
    tmp_path, response_update, stage, token,
):
    response = {
        "p_no": "2", "p_errno": "0", "sCLMID": "CLMDateZyouhou",
        **response_update,
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError) as caught:
        client.provider_calendar_date()
    assert caught.value.classification == ErrorClass.PROVIDER
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == stage
    assert diagnostic["schemaFailureToken"] == token
    assert set(diagnostic) == {
        "operation", "endpointClass", "stage", "classification",
        "httpStatus", "expectedResponseCLMID", "observedResponseCLMID",
        "responseCLMIDMode", "responseListMode", "resultCode",
        "schemaFailureToken", "unexpectedTopLevelFields",
    }
    assert diagnostic["unexpectedTopLevelFields"] == []


def test_date_schema_diagnostic_records_unexpected_field_names_only(tmp_path):
    response = {
        "p_no": "2", "p_errno": "0", "sCLMID": "CLMStkGetDateZyouhou",
        "aCLMDateZyouhou": [{"sDayKey": "001", "sTheDay": "20260903"}],
        "aCLMStkDateZyouhou": [{"sDayKey": "001", "sTheDay": "20260903"}],
        "sSecretLooking": "https://kabuka.e-shiten.jp/e_api_v4r10/x/",
        "bad name=1": "value",
        **{f"sExtra{index}": "v" for index in range(9)},
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    with pytest.raises(TachibanaError) as caught:
        client.provider_calendar_date()
    assert caught.value.classification == ErrorClass.PROVIDER
    diagnostic = client.read_diagnostic_safe_dict()
    assert diagnostic["stage"] == "PROVIDER_DATE_SCHEMA"
    assert diagnostic["schemaFailureToken"] == "TOP_LEVEL_FIELD_UNKNOWN"
    names = diagnostic["unexpectedTopLevelFields"]
    # Sorted, capped at eight, identifier-only; a foreign name is replaced by
    # a marker, and no value, URL, or payload fragment is ever carried.
    assert len(names) == 8
    assert "INVALID_NAME" in names
    # The live-proven echo list key is an accepted Date shape, never foreign.
    assert "aCLMStkDateZyouhou" not in names
    assert "bad name=1" not in names
    assert all(name == "INVALID_NAME" or name.isidentifier() for name in names)
    serialized = json.dumps(diagnostic)
    assert "e-shiten" not in serialized and "value" not in serialized
    assert "20260903" not in serialized


def test_read_diagnostic_rejects_unbounded_or_value_like_field_names():
    with pytest.raises(ValueError):
        ProviderReadDiagnostic(
            operation="CLMStkGetDateZyouhou",
            stage="PROVIDER_DATE_SCHEMA",
            classification="PROVIDER",
            unexpected_top_level_fields=("has space",),
        )
    with pytest.raises(ValueError):
        ProviderReadDiagnostic(
            operation="CLMStkGetDateZyouhou",
            stage="PROVIDER_DATE_SCHEMA",
            classification="PROVIDER",
            unexpected_top_level_fields=tuple(f"f{i}" for i in range(9)),
        )
    with pytest.raises(ValueError):
        ProviderReadDiagnostic(
            operation="CLMStkGetDateZyouhou",
            stage="PROVIDER_DATE_SCHEMA",
            classification="PROVIDER",
            unexpected_top_level_fields=("x" * 41,),
        )


def test_read_diagnostic_rejects_secret_or_market_value_tokens():
    with pytest.raises(ValueError):
        ProviderReadDiagnostic(
            operation="CLMStkGetDateZyouhou",
            stage="PROVIDER_DATE_SCHEMA",
            classification="PROVIDER",
            schema_failure_token="PRIVATEKEYABC123",
        )


@pytest.mark.parametrize("rows", [
    [],
    [
        {"sDayKey": "001", "sTheDay": "20260902"},
        {"sDayKey": "001", "sTheDay": "20260902"},
    ],
    [{"sDayKey": "001", "sTheDay": "20260230"}],
])
def test_provider_calendar_date_fails_closed_on_ambiguous_or_invalid_rows(
    tmp_path, rows,
):
    response = {
        "p_no": "2", "p_errno": "0", "sCLMID": "CLMDateZyouhou",
        "aCLMDateZyouhou": rows,
    }
    session, _, _ = _authenticated_session(tmp_path, [response])
    with pytest.raises(TachibanaError) as caught:
        TachibanaReadOnlyClient(session).provider_calendar_date()
    assert caught.value.classification == ErrorClass.PROVIDER


def test_response_requires_protocol_errno_function_and_bounded_shape(tmp_path):
    invalid = [
        {"p_no": "2", "sCLMID": "CLMMfdsGetMarketPrice",
         "aCLMMfdsMarketPrice": []},
        {"p_no": "3", "p_errno": "0", "sCLMID": "CLMKabuNewOrder"},
        {
            "p_no": "4", "p_errno": "0",
            "sCLMID": "CLMMfdsGetMarketPrice",
            "aCLMMfdsMarketPrice": {},
        },
        {
            "p_no": "5", "p_errno": "0",
            "sCLMID": "CLMMfdsGetMarketPrice",
            "aCLMMfdsMarketPrice": [{"sIssueCode": "7203"}],
        },
        {
            "p_no": "6", "p_errno": "0",
            "sCLMID": "CLMMfdsGetMarketPrice",
            "aCLMMfdsMarketPrice": [], "aOrderList": [],
        },
    ]
    session, _, _ = _authenticated_session(
        tmp_path, invalid, circuit_failure_threshold=10
    )
    client = TachibanaReadOnlyClient(session)
    for _ in invalid:
        with pytest.raises(TachibanaError) as caught:
            client.market_price(("6501",), ("pDPP",))
        assert caught.value.classification == ErrorClass.PROVIDER


@pytest.mark.parametrize("echo", [None, "1", "3", 2])
def test_rest_response_requires_exact_string_request_sequence_echo(
    tmp_path, echo,
):
    response = _success(
        "CLMMfdsGetMarketPrice",
        "aCLMMfdsMarketPrice",
        [{"sIssueCode": "6501", "pDPP": "2000"}],
    )
    if echo is None:
        response.pop("p_no")
    else:
        response["p_no"] = echo
    session, _, _ = _authenticated_session(tmp_path, [response])
    with pytest.raises(TachibanaError) as caught:
        TachibanaReadOnlyClient(session).market_price(("6501",), ("pDPP",))
    assert caught.value.classification == ErrorClass.SEQUENCE_DESYNC
    assert session.state == SessionState.EXPIRED


@pytest.mark.parametrize(("response", "classification", "expired"), [
    ({"p_no": "2", "p_errno": "-2"}, ErrorClass.RATE_LIMITED, False),
    ({"p_no": "2", "p_errno": "-62"}, ErrorClass.OUTSIDE_HOURS, False),
    ({"p_no": "2", "p_errno": "9"}, ErrorClass.MAINTENANCE, False),
    ({"p_no": "2", "p_errno": "6"}, ErrorClass.SEQUENCE_DESYNC, True),
    ({"p_no": "2", "p_errno": "8"}, ErrorClass.CLOCK_SKEW, False),
    ({"p_no": "2", "p_errno": "0", "sResultCode": "990002",
      "sCLMID": "CLMMfdsGetMarketPrice"}, ErrorClass.MAINTENANCE, False),
    ({"p_no": "2", "p_errno": "0", "sResultCode": "990005",
      "sCLMID": "CLMMfdsGetMarketPrice"}, ErrorClass.OUTSIDE_HOURS, False),
    ({"p_no": "2", "p_errno": "0", "sResultCode": "990006",
      "sCLMID": "CLMMfdsGetMarketPrice"}, ErrorClass.SESSION_EXPIRED, True),
    ({"p_no": "2", "p_errno": "0", "sResultCode": "900099",
      "sCLMID": "CLMMfdsGetMarketPrice"}, ErrorClass.PROVIDER, False),
])
def test_protocol_and_business_error_namespaces_do_not_mix(
    tmp_path, response, classification, expired
):
    session, _, _ = _authenticated_session(tmp_path, [response])
    with pytest.raises(TachibanaError) as caught:
        TachibanaReadOnlyClient(session).market_price(("6501",), ("pDPP",))
    assert caught.value.classification == classification
    assert (session.state == SessionState.EXPIRED) is expired


def test_read_retry_is_bounded_and_local_rate_limit_recovers(tmp_path):
    clock = [0.0]
    good_after_retry = _success(
        "CLMMfdsGetMarketPrice", "aCLMMfdsMarketPrice", [{
        "sIssueCode": "6501",
    }], p_no="3")
    good_after_reset = _success(
        "CLMMfdsGetMarketPrice", "aCLMMfdsMarketPrice", [{
        "sIssueCode": "6501",
    }], p_no="4")
    session, transport, _ = _authenticated_session(
        tmp_path,
        [TachibanaError(ErrorClass.NETWORK), good_after_retry, good_after_reset],
        max_requests_per_minute=2,
    )
    sleeps = []
    client = TachibanaReadOnlyClient(
        session, monotonic=lambda: clock[0], sleeper=sleeps.append,
        random_source=lambda: 0.0,
    )
    client.market_price(("6501",), ("pDPP",))
    assert sleeps == [0.25]
    with pytest.raises(TachibanaError) as caught:
        client.market_price(("6501",), ("pDPP",))
    assert caught.value.classification == ErrorClass.RATE_LIMITED
    assert session.state == SessionState.AVAILABLE
    clock[0] = 61.0
    client.market_price(("6501",), ("pDPP",))
    assert session.diagnostics.health.value == "AVAILABLE"
    assert len(transport.calls) == 4


def test_limiter_and_breaker_have_bounded_recoverable_states():
    clock = [0.0]
    limiter = SlidingWindowLimiter(2, 60, clock=lambda: clock[0])
    assert limiter.acquire() and limiter.acquire()
    assert not limiter.acquire()
    clock[0] = 61
    assert limiter.acquire()
    breaker = CircuitBreaker(2, 10, clock=lambda: clock[0])
    breaker.failure(); breaker.failure()
    assert not breaker.permit()
    clock[0] += 11
    assert breaker.permit()
    assert not breaker.permit()
    breaker.success()
    assert breaker.permit()


class FakeHttpResponse:
    def __init__(self, chunks, *, status=200, headers=None):
        self._chunks = chunks
        self.status_code = status
        self.headers = headers or {}
        self.closed = False

    @property
    def content(self):
        raise AssertionError("eager response body access is forbidden")

    def iter_content(self, chunk_size):
        assert chunk_size == 64 * 1024
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeRequestsSession:
    def __init__(self, response):
        self.response = response
        self.trust_env = True
        self.kwargs = None

    def post(self, url, **kwargs):
        self.kwargs = kwargs
        return self.response


class RaisingRequestsSession:
    def __init__(self, error):
        self.error = error
        self.trust_env = True

    def post(self, url, **kwargs):
        raise self.error


def test_http_transport_streams_with_hard_bound_closes_and_ignores_proxy_env():
    raw = json.dumps({"p_errno": "0"}).encode("shift_jis")
    response = FakeHttpResponse([raw], headers={"Content-Length": str(len(raw))})
    http = FakeRequestsSession(response)
    transport = RequestsJsonTransport(http)
    assert http.trust_env is False
    assert transport.post_json("https://example.invalid", {}, 8) == {"p_errno": "0"}
    assert http.kwargs["stream"] is True
    assert http.kwargs["allow_redirects"] is False
    assert response.closed is True

    oversized = FakeHttpResponse([b"x" * (2 * 1024 * 1024), b"x"])
    http = FakeRequestsSession(oversized)
    with pytest.raises(TachibanaError) as caught:
        RequestsJsonTransport(http).post_json("https://example.invalid", {}, 8)
    assert caught.value.classification == ErrorClass.PROVIDER
    assert oversized.closed is True


def test_auth_transport_preserves_http_protocol_and_timeout_boundaries():
    payload = {"sCLMID": "CLMAuthLoginRequest"}
    response = FakeHttpResponse([], status=403)
    transport = RequestsJsonTransport(FakeRequestsSession(response))
    with pytest.raises(TachibanaError) as caught:
        transport.post_json("https://example.invalid", payload, 8)
    assert caught.value.classification == ErrorClass.AUTH_HTTP_FAILED
    assert transport.last_http_status == 403

    invalid = FakeHttpResponse([b"not-json"], status=200)
    with pytest.raises(TachibanaError) as caught:
        RequestsJsonTransport(FakeRequestsSession(invalid)).post_json(
            "https://example.invalid", payload, 8
        )
    assert caught.value.classification == ErrorClass.AUTH_PROTOCOL_FAILED

    with pytest.raises(TachibanaError) as caught:
        RequestsJsonTransport(
            RaisingRequestsSession(requests.Timeout())
        ).post_json("https://example.invalid", payload, 8)
    assert caught.value.classification == ErrorClass.AUTH_TIMEOUT


def test_http_transport_scrubs_credential_paths_from_dependency_debug_logs(caplog):
    response = FakeHttpResponse([json.dumps({"p_errno": "0"}).encode("shift_jis")])
    RequestsJsonTransport(FakeRequestsSession(response))
    virtual_path = "/e_api_v4r10/price/credential-equivalent-token/"

    with caplog.at_level(logging.DEBUG, logger="urllib3.connectionpool"):
        logging.getLogger("urllib3.connectionpool").debug(
            '%s://%s:%s "%s %s HTTP/%s" %s %s',
            "https",
            "price-kabuka.e-shiten.jp",
            443,
            "POST",
            virtual_path,
            "1.1",
            200,
            42,
        )

    rendered = caplog.text
    assert virtual_path not in rendered
    assert "credential-equivalent-token" not in rendered
    assert REDACTED in rendered


def test_http_transport_close_failure_cannot_override_or_expose_result():
    class CloseFailureResponse(FakeHttpResponse):
        def close(self):
            raise RuntimeError(
                "close failed at https://price-kabuka.e-shiten.jp/"
                "e_api_v4r10/price/credential-equivalent-token/"
            )

    raw = json.dumps({"p_errno": "0"}).encode("shift_jis")
    response = CloseFailureResponse([raw], headers={"Content-Length": str(len(raw))})
    transport = RequestsJsonTransport(FakeRequestsSession(response))
    assert transport.post_json("https://example.invalid", {}, 8) == {"p_errno": "0"}


def test_http_transport_total_deadline_stops_bounded_slow_drip():
    clock = [0.0]
    yielded = [0]

    def slow_chunks():
        while True:
            clock[0] += 0.6
            yielded[0] += 1
            yield b" "

    response = FakeHttpResponse(slow_chunks())
    http = FakeRequestsSession(response)
    transport = RequestsJsonTransport(http, monotonic=lambda: clock[0])
    with pytest.raises(TachibanaError) as caught:
        transport.post_json("https://example.invalid", {}, 2)
    assert caught.value.classification == ErrorClass.NETWORK
    assert yielded[0] == 4
    assert response.closed is True
    # A stalled real socket is polled with a bounded inter-byte read timeout;
    # the monotonic check above separately bounds a peer that keeps dripping.
    assert http.kwargs["timeout"] == (2, 1)


def test_minute_precision_alpha_symbol_and_top_of_book_semantics_are_preserved():
    observation = normalize_market_price(
        _row(sIssueCode="130A"), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.OPEN, market_date_verified=True,
    )
    assert observation.source_timestamp == datetime(
        2026, 9, 1, 6, 0, tzinfo=timezone.utc
    )
    assert observation.source_timestamp_precision == "MINUTE"
    assert observation.fresh_until == datetime(
        2026, 9, 1, 6, 0, 15, tzinfo=timezone.utc
    )
    assert observation.freshness == Freshness.FRESH
    assert observation.endpoint_category == "PRICE"
    assert observation.realtime_classification == "CURRENT_MARKET_SNAPSHOT"
    assert observation.fields["best_ask_volume"] == 900
    assert observation.fields["best_bid_volume"] == 1100
    assert "ask_aggregate_volume" not in observation.fields
    assert [level.price for level in observation.asks] == [2001, 2003]
    assert [level.price for level in observation.bids] == [2000, 1998]
    with pytest.raises(TypeError):
        observation.fields["current_price"] = 1


def test_delayed_quote_has_bounded_fresh_until_and_live_snapshot_is_not_a_bar():
    observation = normalize_market_price(
        _row(**{"tDPP:T": "14:55"}), received_at=NOW,
        market_date=date(2026, 9, 1), market_status=MarketStatus.OPEN,
        market_date_verified=True,
    )
    assert observation.freshness == Freshness.DELAYED
    assert observation.fresh_until == datetime(
        2026, 9, 1, 6, 15, tzinfo=timezone.utc
    )
    canonical = to_canonical_observations(observation)
    assert len(canonical) == 1
    assert canonical[0]["factType"] == "QUOTE"
    assert canonical[0]["freshUntil"] == "2026-09-01T06:15:00Z"


def test_market_data_freshness_is_separate_from_market_phase_confidence():
    unverified = normalize_market_price(
        _row(), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.OPEN,
    )
    assert unverified.source_timestamp is None
    assert unverified.source_timestamp_precision == "UNAVAILABLE"
    assert unverified.freshness == Freshness.UNAVAILABLE
    assert unverified.fresh_until is None
    canonical = to_canonical_observations(unverified)[0]
    assert canonical["freshness"] == truth.UNAVAILABLE
    assert canonical["observedAt"] is None

    with pytest.raises(TachibanaError) as malformed:
        normalize_market_price(
            _row(**{"tDPP:T": "not-a-provider-time"}),
            received_at=NOW,
            market_date=None,
            market_status=MarketStatus.UNKNOWN,
        )
    assert malformed.value.classification == ErrorClass.NORMALIZATION

    unknown = normalize_market_price(
        _row(), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.UNKNOWN, market_date_verified=True,
    )
    assert unknown.source_timestamp is not None
    assert unknown.freshness == Freshness.FRESH
    assert unknown.fresh_until is not None
    # Canonical execution evidence still fails closed while phase is unknown.
    assert to_canonical_observations(unknown)[0]["freshness"] == truth.STALE

    closed = normalize_market_price(
        _row(), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.CLOSED, market_date_verified=True,
    )
    assert closed.freshness == Freshness.FRESH
    assert to_canonical_observations(closed)[0]["freshness"] == truth.STALE


def test_smoke_pass_gate_requires_price_fresh_open_timestamp_and_teardown_inputs():
    usable = normalize_market_price(
        _row(), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.OPEN, market_date_verified=True,
    )
    assert _observation_is_usable_and_fresh(usable, now=NOW)
    assert _smoke_pass_allowed(usable, teardown=True, now=NOW)
    assert not _smoke_pass_allowed(usable, teardown=False, now=NOW)
    assert not _observation_is_usable_and_fresh(
        replace(
            usable, freshness=Freshness.STALE, fresh_until=None,
        ),
        now=NOW,
    )
    missing_price = normalize_market_price(
        _row(pDPP=""), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.OPEN, market_date_verified=True,
    )
    assert not _observation_is_usable_and_fresh(missing_price, now=NOW)


def test_missing_stale_and_malformed_book_fail_or_classify_explicitly():
    stale = normalize_market_price(
        _row(pVWAP="", pQAP=None, **{"tDPP:T": "14:00"}),
        received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.OPEN, market_date_verified=True,
    )
    assert stale.fields["vwap"] is None
    assert stale.field_availability["vwap"] is False
    assert stale.freshness == Freshness.STALE
    assert stale.fresh_until is None
    with pytest.raises(TachibanaError) as caught:
        normalize_market_price(
            _row(pGAP1="2001", pGAP2="2001"), received_at=NOW,
            market_date=date(2026, 9, 1),
        )
    assert caught.value.classification == ErrorClass.NORMALIZATION


def test_live_pressure_uses_fresh_open_same_symbol_top_quote_only():
    observation = normalize_market_price(
        _row(pAV="100", pBV="300"), received_at=NOW,
        market_date=date(2026, 9, 1), market_status=MarketStatus.OPEN,
        market_date_verified=True,
    )
    evidence = build_live_pressure_evidence([observation], now=NOW)
    assert evidence["classification"] == "BUY_PRESSURE"
    assert evidence["instrumentId"] == "JP:TSE:6501"
    assert evidence["rawRetained"] is False
    assert "fields" not in evidence and "asks" not in evidence
    assert build_live_pressure_evidence(
        [replace(
            observation, market_status=MarketStatus.CLOSED,
            freshness=Freshness.STALE, fresh_until=None,
        )], now=NOW
    )["classification"] == "UNAVAILABLE"
    assert build_live_pressure_evidence(
        [observation], now=NOW + timedelta(seconds=6)
    )["classification"] == "UNAVAILABLE"
    other = normalize_market_price(
        _row(sIssueCode="7203"), received_at=NOW,
        market_date=date(2026, 9, 1), market_status=MarketStatus.OPEN,
        market_date_verified=True,
    )
    assert build_live_pressure_evidence(
        [observation, other], now=NOW
    )["classification"] == "UNAVAILABLE"


def test_shadow_adapter_registers_quote_only_and_never_grants_authority():
    registry = truth.ProviderAdapterRegistry()
    register_shadow_adapter(registry)
    description = registry.describe()[0]
    assert description["registrationGrantsAuthority"] is False
    assert {scope["factType"] for scope in description["scopes"]} == {"QUOTE"}
    assert all(scope["authority"] is False for scope in description["scopes"])
    assert "tachibana" not in {
        provider for providers in truth.REPOSITORY_PROVIDER_PRIORITY.values()
        for provider in providers
    }


def test_event_subscription_is_immutable_bounded_and_never_requests_execution():
    subscription = EventSubscription(("6501", "130A"), max_symbols=2)
    assert dict(subscription.row_to_symbol) == {1: "6501", 2: "130A"}
    query = parse_qs(subscription.query_string())
    assert query == {
        "p_rid": ["22"], "p_board_no": ["1000"], "p_eno": ["0"],
        "p_evt_cmd": ["ST,KP,FD,SS,US"],
        "p_issue_code": ["6501,130A"], "p_gyou_no": ["1,2"],
        "p_mkt_code": ["00,00"],
    }
    assert "EC" not in query["p_evt_cmd"][0]
    assert "NS" not in query["p_evt_cmd"][0]
    with pytest.raises(TypeError):
        subscription.row_to_symbol[3] = "7203"
    with pytest.raises(ValueError):
        EventSubscription(("6501", "6501"))


def test_official_event_frame_multirow_snapshot_diff_and_sequences():
    initial = parse_event_frame(_event_frame(
        1, "FD",
        ("p_1_DPP", "2000"), ("t_1_DPP:T", "15:00"),
        ("p_2_DPP", "3000"), ("t_2_DPP:T", "15:00"),
    ))
    assembler = EventSnapshotAssembler(
        row_to_symbol={1: "6501", 2: "7203"}, max_symbols=2
    )
    rows = assembler.apply(initial)
    assert [row["sIssueCode"] for row in rows] == ["6501", "7203"]
    assert rows[0]["pDPP"] == "2000"
    with pytest.raises(TypeError):
        rows[0]["pDPP"] = "1"
    diff = parse_event_frame(_event_frame(2, "FD", ("p_1_DV", "1000")))
    changed, = assembler.apply(diff)
    assert changed["pDPP"] == "2000"
    assert changed["pDV"] == "1000"
    with pytest.raises(ValueError, match="gap"):
        assembler.apply(parse_event_frame(
            _event_frame(4, "FD", ("p_1_DV", "1001"))
        ))


def test_event_parser_rejects_execution_request_key_and_partial_initial():
    with pytest.raises(ValueError, match="not_read_only"):
        parse_event_frame(_event_frame(1, "EC", ("p_ENO", "101")))
    with pytest.raises(ValueError, match="missing"):
        parse_event_frame(
            "p_no\x021\x01p_date\x022026.09.01-15:00:10.123\x01"
            "p_evt_cmd\x02FD\x01"
        )
    assembler = EventSnapshotAssembler(
        row_to_symbol={1: "6501", 2: "7203"}, max_symbols=2
    )
    with pytest.raises(ValueError, match="incomplete"):
        assembler.apply(parse_event_frame(
            _event_frame(1, "FD", ("p_1_DPP", "2000"))
        ))


def test_system_event_numbers_are_uppercase_ascending_not_consecutive():
    assembler = EventSnapshotAssembler(row_to_symbol={1: "6501"}, max_symbols=1)
    assert assembler.apply(parse_event_frame(
        _ss_frame(1, 100)
    )) == ()
    assert assembler.apply(parse_event_frame(
        _us_frame(2, 105)
    )) == ()
    # p_ENO is ascending but non-consecutive.  It orders notifications, while
    # p_CT orders the underlying state represented by an SS/US notification.
    with pytest.raises(ValueError, match="not_ascending"):
        assembler.apply(parse_event_frame(_ss_frame(3, 104)))
    with pytest.raises(ValueError, match="invalid"):
        parse_event_frame(_event_frame(1, "SS", ("p_eno", "1")))


@pytest.mark.parametrize("event_number", [99, 100])
def test_system_event_number_lower_or_equal_fails_within_connection(
    event_number,
):
    assembler = EventSnapshotAssembler(row_to_symbol={1: "6501"}, max_symbols=1)
    assert assembler.apply(parse_event_frame(_ss_frame(1, 100))) == ()
    with pytest.raises(ValueError, match="not_ascending"):
        assembler.apply(parse_event_frame(_us_frame(2, event_number)))


def test_event_text_encoding_contract_is_field_scoped_and_bounded():
    japanese = "東証一部"
    encoded = base64.b64encode(japanese.encode("shift_jis")).decode("ascii")
    assert decode_event_base64_shift_jis(encoded) == japanese
    with pytest.raises(ValueError, match="invalid"):
        decode_event_base64_shift_jis("not-base64!")
    with pytest.raises(ValueError, match="too_large"):
        decode_event_base64_shift_jis(encoded, maximum_decoded_bytes=2)

    # Japanese Base64 fields belong only to EC/NS and cannot make either
    # forbidden command reachable through this market-data parser.
    with pytest.raises(ValueError, match="not_read_only"):
        parse_event_frame(_event_frame(1, "NS", ("p_HDL", encoded)))

    listing_hex = japanese.encode("shift_jis").hex().upper()
    parsed = parse_event_frame(_event_frame(1, "FD", ("x_1_LISS", listing_hex)))
    assert parsed["x_1_LISS"] == listing_hex
    with pytest.raises(ValueError, match="shift_jis"):
        parse_event_frame(_event_frame(1, "FD", ("x_1_LISS", "8")))
    with pytest.raises(ValueError, match="malformed"):
        parse_event_frame(_event_frame(1, "FD", ("p_1_DPP", "1\x032")))


def test_event_status_shapes_are_exact_and_connection_sequence_starts_at_one():
    assert parse_event_frame(_ss_frame(1, 1))["p_SS"] == "0"
    assert parse_event_frame(_us_frame(2, 2))["p_US"] == "200"
    with pytest.raises(ValueError, match="fields_invalid"):
        parse_event_frame(
            _ss_frame(1, 1).replace("\x01", "\x01p_evil\x021\x01", 1)
        )
    with pytest.raises(ValueError, match="field_value"):
        parse_event_frame(_ss_frame(1, 1, login_permission="7"))
    with pytest.raises(ValueError, match="operation_field_value"):
        parse_event_frame(_us_frame(1, 1, market="03"))
    assembler = EventSnapshotAssembler(row_to_symbol={1: "6501"}, max_symbols=1)
    with pytest.raises(ValueError, match="gap"):
        assembler.apply(parse_event_frame(
            _event_frame(2, "FD", ("p_1_DPP", "2000"))
        ))


def test_status_tracker_uses_provider_time_and_never_invents_market_open():
    tracker = EventStatusTracker()
    available = tracker.apply(parse_event_frame(_ss_frame(
        1, 100, provider_time="20260901150000",
    )))
    assert available.provider_health == ProviderHealth.AVAILABLE

    # A replayed older status must not roll current health backwards even if
    # its p_ENO and connection arrival order are later.
    ignored = tracker.apply(parse_event_frame(_ss_frame(
        2, 105, provider_time="20260901140000",
        login_permission="0", system_status="1",
    )))
    assert ignored.provider_health == ProviderHealth.AVAILABLE

    preopen = tracker.apply(parse_event_frame(_us_frame(
        3, 110, provider_time="20260901150100", operation_status="100",
    )))
    assert preopen.market_status == MarketStatus.UNKNOWN
    lunch = tracker.apply(parse_event_frame(_us_frame(
        4, 111, provider_time="20260901150200", operation_status="140",
    )))
    assert lunch.market_status == MarketStatus.CLOSED
    fault = tracker.apply(parse_event_frame(_us_frame(
        5, 112, provider_time="20260901150300", operation_status="898",
    )))
    assert fault.market_status == MarketStatus.UNKNOWN
    assert fault.provider_health == ProviderHealth.DEGRADED
    fault_truth = resolve_jp_cash_session(
        now=datetime(2026, 9, 1, 6, 3, tzinfo=timezone.utc),
        provider_time=datetime(2026, 9, 1, 6, 3, tzinfo=timezone.utc),
        provider_calendar_date=date(2026, 9, 1),
        provider_health=fault.provider_health,
        provider_market_status=fault.market_status,
    )
    assert fault_truth.market_date_verified is True
    assert fault_truth.phase == JapanCashPhase.UNKNOWN
    assert fault_truth.session_truth_confident is False
    halted = tracker.apply(parse_event_frame(_us_frame(
        6, 113, provider_time="20260901150400", business_day="2",
    )))
    assert halted.market_status == MarketStatus.HALTED


def test_ss_replay_uses_per_provider_p_ct_and_separates_closure_from_health():
    tracker = EventStatusTracker(provider_calendar_date=date(2026, 9, 2))
    closed_system = tracker.apply(parse_event_frame(_ss_frame(
        1, 1, provider_time="20260902052959",
        login_permission="1", system_status="1",
    )))
    assert closed_system.provider_health == ProviderHealth.AVAILABLE
    assert closed_system.system_status_code == "1"
    assert closed_system.login_permission_code == "1"
    assert closed_system.market_status == MarketStatus.UNKNOWN
    assert closed_system.status_date_verified is True

    opened = tracker.apply(parse_event_frame(_ss_frame(
        2, 2, provider_time="20260902075500",
        login_permission="1", system_status="0",
    )))
    assert opened.provider_health == ProviderHealth.AVAILABLE
    assert opened.system_status_code == "0"

    # Later receive order and p_ENO cannot roll the same logical key back.
    ignored = tracker.apply(parse_event_frame(_ss_frame(
        3, 3, provider_time="20260902060000",
        login_permission="0", system_status="1",
    )))
    assert ignored.provider_health == ProviderHealth.AVAILABLE
    assert ignored.system_status_code == "0"


def test_us_replay_is_per_full_operation_key_and_aggregated_fail_closed():
    tracker = EventStatusTracker(provider_calendar_date=date(2026, 9, 2))
    cash = tracker.apply(parse_event_frame(_us_frame(
        1, 1, provider_time="20260902080000", operation_status="100",
    )))
    assert cash.operation_code == "100"
    assert cash.market_status == MarketStatus.UNKNOWN

    # A newer derivatives key legitimately coexists and cannot overwrite the
    # Tokyo cash-equity state.
    unrelated = tracker.apply(parse_event_frame(_us_frame(
        2, 2, provider_time="20260902100000", market="01",
        group_code="101", section="03", unit="0201", category="02",
        operation_status="900",
    )))
    assert unrelated.operation_code == "100"
    assert unrelated.market_status == MarketStatus.UNKNOWN
    assert len(tracker._operation_states) == 2

    closed = tracker.apply(parse_event_frame(_us_frame(
        3, 3, provider_time="20260902113000", operation_status="140",
    )))
    assert closed.operation_code == "140"
    assert closed.market_status == MarketStatus.CLOSED

    # A second relevant Tokyo key with a live acceptance state makes the
    # aggregate ambiguous, never arrival-order OPEN or CLOSED.
    mixed = tracker.apply(parse_event_frame(_us_frame(
        4, 4, provider_time="20260902120500", market="01",
        operation_status="200",
    )))
    assert mixed.operation_code is None
    assert mixed.market_status == MarketStatus.UNKNOWN


def test_stale_status_date_cannot_negate_current_fd_but_current_maintenance_can():
    tracker = EventStatusTracker(provider_calendar_date=date(2026, 9, 2))
    stale = tracker.apply(parse_event_frame(_ss_frame(
        1, 1, provider_time="20260901235900",
        login_permission="0", system_status="1",
    )))
    assert stale.provider_health == ProviderHealth.AVAILABLE
    assert stale.status_date_verified is False
    current_fd = tracker.apply(parse_event_frame(_event_frame(
        2, "FD", ("p_1_DPP", "2000"),
        p_date="2026.09.02-09:00:00.000",
    )))
    assert current_fd.provider_health == ProviderHealth.AVAILABLE

    maintenance = tracker.apply(parse_event_frame(_ss_frame(
        3, 2, provider_time="20260902090001",
        login_permission="0", system_status="1",
    )))
    assert maintenance.provider_health == ProviderHealth.MAINTENANCE
    assert maintenance.market_status == MarketStatus.MAINTENANCE
    assert tracker.apply(parse_event_frame(_event_frame(
        4, "KP", p_date="2026.09.02-09:00:05.000"
    ))).provider_health == ProviderHealth.MAINTENANCE


def test_equal_p_ct_conflict_is_degraded_until_a_newer_state_supersedes_it():
    tracker = EventStatusTracker(provider_calendar_date=date(2026, 9, 2))
    tracker.apply(parse_event_frame(_us_frame(
        1, 1, provider_time="20260902080000", operation_status="100",
    )))
    conflict = tracker.apply(parse_event_frame(_us_frame(
        2, 2, provider_time="20260902080000", operation_status="140",
    )))
    assert conflict.state_conflict is True
    assert conflict.provider_health == ProviderHealth.DEGRADED
    assert conflict.market_status == MarketStatus.UNKNOWN
    now = datetime(2026, 9, 2, 0, 1, tzinfo=timezone.utc)
    unresolved = resolve_jp_cash_session(
        now=now,
        provider_time=now,
        provider_calendar_date=date(2026, 9, 2),
        provider_health=conflict.provider_health,
        provider_market_status=conflict.market_status,
        control_state_confident=not conflict.state_conflict,
    )
    assert unresolved.market_date_verified is True
    assert unresolved.session_truth_confident is False
    assert unresolved.phase == JapanCashPhase.UNKNOWN

    recovered = tracker.apply(parse_event_frame(_us_frame(
        3, 3, provider_time="20260902080001", operation_status="100",
    )))
    assert recovered.state_conflict is False
    assert recovered.provider_health == ProviderHealth.AVAILABLE
    assert recovered.operation_code == "100"


def test_status_tracker_retains_bounded_per_key_operation_state():
    tracker = EventStatusTracker()
    ignored = tracker.apply(parse_event_frame(_us_frame(
        1, 1, unit="0102", operation_status="140",
    )))
    assert ignored.market_status == MarketStatus.UNKNOWN
    assert len(tracker._operation_states) == 1

    for index in range(63):
        snapshot = tracker.apply(parse_event_frame(_us_frame(
            index + 2,
            index + 2,
            group_code=f"{index:03d}",
            operation_status="140",
        )))
        # Non-cash logical keys are retained for chronology but cannot close
        # the Tokyo cash-equity market globally.
        assert snapshot.market_status == MarketStatus.UNKNOWN
    assert len(tracker._operation_states) == 64

    overflow = tracker.apply(parse_event_frame(_us_frame(
        65, 65, group_code="064", operation_status="140",
    )))
    assert len(tracker._operation_states) == 64
    assert overflow.market_status == MarketStatus.UNKNOWN
    assert overflow.provider_health == ProviderHealth.DEGRADED


def test_event_parser_ignores_safe_unknown_extensions_but_keeps_critical_bounds():
    assembler = EventSnapshotAssembler(
        row_to_symbol={1: "6501"}, max_symbols=1
    )
    parsed = parse_event_frame(_event_frame(
        1, "FD", ("p_1_DPP", "2000"), ("p_1_FUTURE", "opaque")
    ))
    row, = assembler.apply(parsed)
    assert row["pDPP"] == "2000"
    assert "pFUTURE" not in row

    keepalive = parse_event_frame(_event_frame(2, "KP", ("p_FUTURE", "1")))
    assert keepalive["p_FUTURE"] == "1"
    system = parse_event_frame(
        _ss_frame(3, 3)[:-1] + "\x01p_FUTURE\x021\x01"
    )
    assert system["p_FUTURE"] == "1"

    with pytest.raises(ValueError, match="row_not_subscribed"):
        assembler.apply(parse_event_frame(_event_frame(
            2, "FD", ("p_2_FUTURE", "opaque")
        )))
    with pytest.raises(ValueError, match="field_invalid"):
        parse_event_frame(_event_frame(2, "FD", ("p_FUTURE", "opaque")))


def test_keepalive_cannot_override_explicit_unavailable_system_status():
    tracker = EventStatusTracker()
    unavailable = tracker.apply(parse_event_frame(_ss_frame(
        1, 1, login_permission="2", system_status="1",
    )))
    assert unavailable.provider_health == ProviderHealth.UNAVAILABLE
    keepalive = tracker.apply(parse_event_frame(_event_frame(2, "KP")))
    assert keepalive.provider_health == ProviderHealth.UNAVAILABLE


def test_receive_only_websocket_connector_builds_exact_bounded_private_dial():
    frame = _event_frame(1, "KP")
    connection = FakeWebSocketConnection([frame])
    calls = []

    def connect(uri, **kwargs):
        calls.append((uri, kwargs))
        return connection

    connector = WebSocketEventConnector(connect)
    stop = threading.Event()
    stream = iter(connector.receive(
        _virtual_urls()["sUrlEventWebSocket"],
        EventSubscription(("6501", "130A"), max_symbols=2),
        connect_timeout_seconds=8,
        idle_timeout_seconds=30,
        maximum_frame_bytes=1024,
        stop_event=stop,
    ))
    assert next(stream) == frame
    stop.set()
    with pytest.raises(StopIteration):
        next(stream)
    assert connection.closed is True
    assert not hasattr(connector, "send")

    uri, options = calls[0]
    query = parse_qs(urlsplit(uri).query)
    assert query == {
        "p_rid": ["22"], "p_board_no": ["1000"], "p_eno": ["0"],
        "p_evt_cmd": ["ST,KP,FD,SS,US"],
        "p_issue_code": ["6501,130A"], "p_gyou_no": ["1,2"],
        "p_mkt_code": ["00,00"],
    }
    assert options["max_size"] == 1024
    assert options["max_queue"] == 1
    assert options["compression"] is None
    assert options["ping_interval"] is None
    assert options["proxy"] is None
    assert options["logger"].disabled is True


@pytest.mark.parametrize("message", [b"binary", "x" * 11])
def test_websocket_connector_rejects_binary_and_post_dial_oversize(message):
    connection = FakeWebSocketConnection([message])
    connector = WebSocketEventConnector(lambda _uri, **_kwargs: connection)
    stream = connector.receive(
        _virtual_urls()["sUrlEventWebSocket"], EventSubscription(("6501",)),
        connect_timeout_seconds=8, idle_timeout_seconds=30,
        maximum_frame_bytes=10, stop_event=threading.Event(),
    )
    with pytest.raises(TachibanaError) as caught:
        next(iter(stream))
    assert caught.value.classification == ErrorClass.PROVIDER
    assert connection.closed is True


def test_websocket_connector_idle_timeout_and_errors_never_expose_virtual_url():
    endpoint = _virtual_urls()["sUrlEventWebSocket"]
    ticks = iter((0.0, 0.0, 5.1))
    timeout_connection = FakeWebSocketConnection([TimeoutError()])
    connector = WebSocketEventConnector(
        lambda _uri, **_kwargs: timeout_connection,
        monotonic=lambda: next(ticks),
    )
    stream = connector.receive(
        endpoint, EventSubscription(("6501",)), connect_timeout_seconds=8,
        idle_timeout_seconds=5, maximum_frame_bytes=1024,
        stop_event=threading.Event(),
    )
    with pytest.raises(TachibanaError) as caught:
        list(stream)
    assert caught.value.classification == ErrorClass.EVENT_IDLE_TIMEOUT
    assert isinstance(caught.value, EventTransportError)
    assert caught.value.timeout_category == "IDLE"
    assert endpoint not in str(caught.value)

    def failed_dial(uri, **_kwargs):
        raise RuntimeError(uri)

    failed = WebSocketEventConnector(failed_dial)
    with pytest.raises(TachibanaError) as dial_error:
        failed.receive(
            endpoint, EventSubscription(("6501",)), connect_timeout_seconds=8,
            idle_timeout_seconds=5, maximum_frame_bytes=1024,
            stop_event=threading.Event(),
        )
    assert dial_error.value.classification == ErrorClass.NETWORK
    assert endpoint not in str(dial_error.value)


def test_websocket_close_diagnostics_are_bounded_and_reason_is_redacted():
    class CloseFrame:
        code = 1011
        reason = "credential-shaped provider detail must not survive"

    class Closed(RuntimeError):
        rcvd = CloseFrame()

    connection = FakeWebSocketConnection([Closed("raw close payload")])
    connector = WebSocketEventConnector(lambda _uri, **_kwargs: connection)
    stream = connector.receive(
        _virtual_urls()["sUrlEventWebSocket"],
        EventSubscription(("6501",)),
        connect_timeout_seconds=8,
        idle_timeout_seconds=30,
        maximum_frame_bytes=1024,
        stop_event=threading.Event(),
    )
    with pytest.raises(EventTransportError) as caught:
        list(stream)
    assert caught.value.close_code == 1011
    assert caught.value.close_reason_classification == "PRESENT_REDACTED"
    assert "credential-shaped" not in str(caught.value)


def test_websocket_connect_timeout_is_classified_without_endpoint_exposure():
    endpoint = _virtual_urls()["sUrlEventWebSocket"]

    def timed_out(_uri, **_kwargs):
        raise TimeoutError("secret-shaped timeout detail")

    connector = WebSocketEventConnector(timed_out)
    with pytest.raises(EventTransportError) as caught:
        connector.receive(
            endpoint,
            EventSubscription(("6501",)),
            connect_timeout_seconds=8,
            idle_timeout_seconds=30,
            maximum_frame_bytes=1024,
            stop_event=threading.Event(),
        )
    assert caught.value.classification == ErrorClass.NETWORK
    assert caught.value.timeout_category == "CONNECT"
    assert endpoint not in str(caught.value)


def test_websocket_policy_is_disabled_and_reconnect_budget_resets_on_tokyo_day():
    policy = EventConnectionPolicy.from_config(TachibanaConfig())
    assert policy.enabled is False
    assert policy.maximum_frame_bytes == 256 * 1024
    clock = [datetime(2026, 9, 1, 14, 59, tzinfo=timezone.utc)]
    budget = EventReconnectBudget(2, clock=lambda: clock[0])
    assert budget.consume() and budget.consume()
    assert not budget.consume()
    clock[0] += timedelta(minutes=2)
    assert budget.consume()


def test_event_lifecycle_is_disabled_before_endpoint_or_dial(tmp_path):
    session, _, _ = _authenticated_session(tmp_path)
    connector = ScriptedEventConnector([])
    lifecycle = TachibanaEventLifecycle(
        session,
        EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=connector,
        # A caller-constructed policy cannot bypass the environment gate.
        policy=EventConnectionPolicy(enabled=True, connect_timeout_seconds=8),
    )
    # If the lifecycle attempted endpoint access this expired session would
    # produce SESSION_EXPIRED instead of the feature-gate result.
    session.expire()
    with pytest.raises(TachibanaError) as caught:
        lifecycle.run(threading.Event())
    assert caught.value.classification == ErrorClass.DISABLED
    assert connector.calls == []


def test_event_lifecycle_uses_one_conservative_process_wide_connection_lock(
    tmp_path,
):
    session1, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    session2, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    lifecycle1 = TachibanaEventLifecycle(
        session1,
        EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=ScriptedEventConnector([]),
    )
    lifecycle2 = TachibanaEventLifecycle(
        session2,
        EventSubscription(("7203",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=ScriptedEventConnector([]),
    )
    # Tachibana permits one EVENT connection per customer.  Without reading or
    # retaining a customer identifier, the only provably safe local policy is
    # one EVENT connection for the entire process, including distinct sessions.
    assert lifecycle1._run_lock is lifecycle2._run_lock


def test_event_lifecycle_ingests_fd_through_assembler_and_normalizer(tmp_path):
    session, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    stop = threading.Event()

    def successful(owned_stop):
        yield _ss_frame(1, 100)
        yield _us_frame(2, 105, operation_status="200")
        yield _event_frame(
            3, "FD",
            ("p_1_DPP", "2000"), ("t_1_DPP:T", "15:00"),
            ("p_1_QAP", "2001"), ("p_1_AV", "900"),
            ("p_1_QBP", "2000"), ("p_1_BV", "1100"),
        )
        owned_stop.set()

    connector = ScriptedEventConnector([successful])
    sensor = TransientLiveSensor(max_symbols=1, window_size=4, window_seconds=30)
    lifecycle = TachibanaEventLifecycle(
        session, EventSubscription(("6501",)), sensor,
        connector=connector, clock=lambda: NOW,
    )
    summary = lifecycle.run(stop)
    assert summary.connections_started == 1
    assert summary.reconnects == 0
    assert summary.frames_received == 3
    assert summary.observations_ingested == 1
    assert summary.provider_health == ProviderHealth.AVAILABLE
    # US 200 is an order-acceptance transition at about 12:05, not proof that
    # the TSE afternoon session is open.
    assert summary.market_status == MarketStatus.UNKNOWN
    observation = sensor.latest("6501", now=NOW)
    assert observation is not None
    assert observation.endpoint_category == "EVENT"
    assert observation.market_status == MarketStatus.UNKNOWN
    # EVENT publishes only HH:MM trade time and no verified trading-calendar
    # date or exchange-open transition.  It must stay non-authoritative rather
    # than relabel a prior-session tick as current.
    assert observation.source_timestamp is None
    assert observation.freshness == Freshness.UNAVAILABLE
    assert observation.fresh_until is None
    assert observation.fields["best_ask_volume"] == 900.0
    assert observation.fields["best_bid_volume"] == 1100.0
    assert session.diagnostics.websocket_connected is False


def test_event_lifecycle_reconnects_on_sequence_gap_and_requires_new_sequence_one(
    tmp_path,
):
    session, _, _ = _authenticated_session(
        tmp_path, websocket_enabled=True, max_event_reconnects_per_day=2,
    )
    stop = threading.Event()
    initial = _event_frame(
        1, "FD", ("p_1_DPP", "2000"), ("t_1_DPP:T", "15:00"),
    )
    gap = _event_frame(3, "FD", ("p_1_DV", "100"))
    wrong_new_start = _event_frame(
        2, "FD", ("p_1_DPP", "2001"), ("t_1_DPP:T", "15:00"),
    )

    def recovered(owned_stop):
        yield _event_frame(
            1, "FD", ("p_1_DPP", "2002"), ("t_1_DPP:T", "15:00"),
        )
        owned_stop.set()

    connector = ScriptedEventConnector([
        (initial, gap), (wrong_new_start,), recovered,
    ])
    delays = []
    sensor = TransientLiveSensor(max_symbols=1, window_size=4, window_seconds=30)
    lifecycle = TachibanaEventLifecycle(
        session, EventSubscription(("6501",)), sensor,
        connector=connector, clock=lambda: NOW, random_value=lambda: 0.0,
        waiter=lambda _stop, delay: delays.append(delay) or False,
    )
    summary = lifecycle.run(stop)
    assert summary.connections_started == 3
    assert summary.reconnects == 2
    assert summary.last_error == ErrorClass.NONE
    # v13.5.39: after an established connection closes the lifecycle first
    # waits for the provider's disconnect processing (5 s drain), then backs
    # off 5 s, 10 s, ... for the SAME-SESSION reconnect (no re-authentication).
    assert delays == [5.0, 5.0, 5.0, 10.0]
    assert sensor.latest("6501", now=NOW).fields["current_price"] == 2002.0


def test_event_lifecycle_uses_current_session_truth_for_fresh_observation(
    tmp_path,
):
    current = datetime(2026, 9, 2, 0, 0, 10, 123000, tzinfo=timezone.utc)
    session, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    stop = threading.Event()

    def frames(owned_stop):
        yield _event_frame(
            1,
            "FD",
            ("p_1_DPP", "2000"),
            ("t_1_DPP:T", "09:00"),
            p_date="2026.09.02-09:00:10.123",
        )
        owned_stop.set()

    sensor = TransientLiveSensor(max_symbols=1, window_size=4, window_seconds=30)
    lifecycle = TachibanaEventLifecycle(
        session,
        EventSubscription(("6501",)),
        sensor,
        connector=ScriptedEventConnector([frames]),
        clock=lambda: current,
        session_truth_resolver=resolve_jp_cash_session,
        provider_calendar_date=date(2026, 9, 2),
    )
    summary = lifecycle.run(stop)
    observation = sensor.latest("6501", now=current)
    assert summary.observations_ingested == 1
    assert observation.market_status == MarketStatus.OPEN
    assert observation.freshness == Freshness.FRESH
    assert observation.source_timestamp == datetime(
        2026, 9, 2, 0, 0, tzinfo=timezone.utc
    )


def test_session_three_safe_shape_reconciles_ss_closed_with_live_cash_fd(
    tmp_path,
):
    current = datetime(2026, 9, 2, 1, 19, 10, tzinfo=timezone.utc)
    event_date = "2026.09.02-10:19:10.000"
    session, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    stop = threading.Event()

    def frames(owned_stop):
        yield _ss_frame(
            1, 1, provider_time="20260902052959",
            login_permission="1", system_status="1",
            event_date=event_date,
        )
        yield _us_frame(
            2, 2, provider_time="20260902064500", market="01",
            group_code="101", section="03", unit="0201", category="02",
            operation_status="100", event_date=event_date,
        )
        yield _us_frame(
            3, 3, provider_time="20260902064501", market="01",
            group_code="101", section="04", unit="0202", category="02",
            operation_status="100", event_date=event_date,
        )
        yield _us_frame(
            4, 4, provider_time="20260902070000", unit="0500",
            category="05", section="05", operation_status="000",
            event_date=event_date,
        )
        yield _us_frame(
            5, 5, provider_time="20260902070001", unit="1100",
            category="11", operation_status="000", event_date=event_date,
        )
        yield _us_frame(
            6, 6, provider_time="20260902080000", operation_status="100",
            event_date=event_date,
        )
        yield _event_frame(
            7, "FD", ("p_1_DPP", "2000"),
            ("t_1_DPP:T", "10:19"), ("p_1_QAP", "2001"),
            ("p_1_QBP", "2000"), p_date=event_date,
        )
        owned_stop.set()

    progress = EventLifecycleProgress()
    sensor = TransientLiveSensor(max_symbols=1, window_size=4, window_seconds=30)
    lifecycle = TachibanaEventLifecycle(
        session,
        EventSubscription(("6501",)),
        sensor,
        connector=ScriptedEventConnector([frames]),
        clock=lambda: current,
        session_truth_resolver=resolve_jp_cash_session,
        provider_calendar_date=date(2026, 9, 2),
        progress=progress,
    )
    summary = lifecycle.run(stop)
    snapshot = progress.snapshot()
    observation = sensor.latest("6501", now=current)
    assert summary.reconnects == 0
    assert summary.provider_health == ProviderHealth.AVAILABLE
    assert snapshot.ss_frames == 1
    assert snapshot.us_frames == 5
    assert snapshot.fd_frames == 1
    assert snapshot.provider_login_permission_code == "1"
    assert snapshot.provider_system_status_code == "1"
    assert snapshot.provider_operation_code == "100"
    assert snapshot.provider_status_date_verified is True
    assert observation.market_status == MarketStatus.OPEN
    assert observation.freshness == Freshness.FRESH
    assert observation.market_data_date_verified is True


def test_noncritical_fd_normalization_degrades_field_without_reconnect(tmp_path):
    current = datetime(2026, 9, 2, 0, 1, 10, tzinfo=timezone.utc)
    session, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    stop = threading.Event()

    def frames(owned_stop):
        yield _event_frame(
            1, "FD", ("p_1_DPP", "not-a-number"),
            ("t_1_DPP:T", "09:01"), ("p_1_QAP", "2001"),
            ("p_1_QBP", "2000"),
            p_date="2026.09.02-09:01:10.000",
        )
        owned_stop.set()

    progress = EventLifecycleProgress()
    sensor = TransientLiveSensor(max_symbols=1, window_size=4, window_seconds=30)
    summary = TachibanaEventLifecycle(
        session,
        EventSubscription(("6501",)),
        sensor,
        connector=ScriptedEventConnector([frames]),
        clock=lambda: current,
        session_truth_resolver=resolve_jp_cash_session,
        provider_calendar_date=date(2026, 9, 2),
        progress=progress,
    ).run(stop)
    observation = sensor.latest("6501", now=current)
    safe = progress.snapshot()
    assert summary.reconnects == 0
    assert summary.observations_ingested == 1
    assert observation.fields["current_price"] is None
    assert observation.field_availability["current_price"] is False
    assert observation.freshness == Freshness.FRESH
    assert safe.normalization_degradations == 1
    assert safe.last_normalization_field == "PDPP"
    assert safe.last_normalization_reason == "INVALID_NUMBER"
    assert safe.last_normalization_row == 1
    assert safe.last_normalization_symbol == "6501"


def test_event_lifecycle_has_daily_reconnect_exhaustion_and_terminal_st(tmp_path):
    session, _, _ = _authenticated_session(
        tmp_path, websocket_enabled=True, max_event_reconnects_per_day=1,
    )
    connector = ScriptedEventConnector([(), ()])
    progress = EventLifecycleProgress()
    lifecycle = TachibanaEventLifecycle(
        session,
        EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=connector, clock=lambda: NOW, random_value=lambda: 0.0,
        waiter=lambda _stop, _delay: False,
        progress=progress,
    )
    with pytest.raises(TachibanaError) as exhausted:
        lifecycle.run(threading.Event())
    assert exhausted.value.classification == ErrorClass.EVENT_RECONNECT_EXHAUSTED
    assert len(connector.calls) == 2
    exhausted_progress = progress.snapshot()
    assert exhausted_progress.connections_started == 2
    assert exhausted_progress.reconnects_scheduled == 1
    assert exhausted_progress.last_failure_classification == "NETWORK"
    assert exhausted_progress.last_failure_detail == "NETWORK"

    session2, _, _ = _authenticated_session(tmp_path, websocket_enabled=True)
    terminal = ScriptedEventConnector([(
        _event_frame(1, "ST", ("p_errno", "2"), ("p_err", "session inactive.")),
    )])
    lifecycle2 = TachibanaEventLifecycle(
        session2,
        EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=terminal, clock=lambda: NOW,
    )
    with pytest.raises(TachibanaError) as inactive:
        lifecycle2.run(threading.Event())
    assert inactive.value.classification == ErrorClass.SESSION_EXPIRED
    assert session2.state == SessionState.EXPIRED
    assert len(terminal.calls) == 1


class _ConnectFailingConnector:
    """Fails at CONNECT with a NETWORK transport error, N times, then serves."""

    def __init__(self, failures, then=()):
        self.failures = failures
        self.then = list(then)
        self.calls = 0

    def receive(self, endpoint, subscription, **kwargs):
        self.calls += 1
        if self.calls <= self.failures:
            raise EventTransportError(ErrorClass.NETWORK, timeout_category="CONNECT")
        return iter(self.then.pop(0) if self.then else ())


def test_event_policy_defaults_follow_official_contract_recovery_order():
    policy = EventConnectionPolicy.from_config(
        TachibanaConfig(websocket_enabled=True, max_event_reconnects_per_day=3))
    assert policy.reconnect_initial_seconds == 5.0
    assert policy.reconnect_maximum_seconds == 60.0
    assert policy.drain_wait_seconds == 5.0
    assert policy.outage_backoff_seconds == 30.0
    assert policy.outage_budget_seconds == 900.0
    with pytest.raises(ValueError):
        EventConnectionPolicy(enabled=True, connect_timeout_seconds=8,
                              outage_budget_seconds=10.0)
    with pytest.raises(ValueError):
        EventConnectionPolicy(enabled=True, connect_timeout_seconds=8,
                              drain_wait_seconds=31.0)


def test_event_connect_failure_with_unreachable_transport_waits_without_spending_budget(tmp_path):
    session, _, _ = _authenticated_session(
        tmp_path, websocket_enabled=True, max_event_reconnects_per_day=1,
    )
    connector = _ConnectFailingConnector(failures=99)
    progress = EventLifecycleProgress()
    delays = []
    probes = []
    policy = EventConnectionPolicy(
        enabled=True, connect_timeout_seconds=8, maximum_reconnects_per_day=1,
        outage_backoff_seconds=30.0, outage_budget_seconds=60.0)
    lifecycle = TachibanaEventLifecycle(
        session, EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=connector, clock=lambda: NOW, random_value=lambda: 0.0,
        waiter=lambda _stop, delay: delays.append(delay) or False,
        progress=progress, policy=policy,
        reachability_probe=lambda endpoint: probes.append(endpoint) or False,
    )
    with pytest.raises(TachibanaError) as exhausted:
        lifecycle.run(threading.Event())
    # Two 30 s outage waits fit the 60 s budget; the third exceeds it.  The
    # single daily reconnect was never consumed and no re-authentication ran.
    assert exhausted.value.classification == ErrorClass.EVENT_RECONNECT_EXHAUSTED
    assert delays == [30.0, 30.0]
    assert connector.calls == 3
    snapshot = progress.snapshot()
    assert snapshot.transport_unreachable_waits == 2
    assert snapshot.reconnects_scheduled == 0
    assert session.state == SessionState.AVAILABLE
    assert len(probes) == 3 and all(p.startswith("wss://") for p in probes)


def test_event_connect_failure_with_reachable_transport_consumes_reconnect_budget(tmp_path):
    session, _, _ = _authenticated_session(
        tmp_path, websocket_enabled=True, max_event_reconnects_per_day=1,
    )
    connector = _ConnectFailingConnector(failures=99)
    progress = EventLifecycleProgress()
    delays = []
    lifecycle = TachibanaEventLifecycle(
        session, EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=connector, clock=lambda: NOW, random_value=lambda: 0.0,
        waiter=lambda _stop, delay: delays.append(delay) or False,
        progress=progress, reachability_probe=lambda endpoint: True,
    )
    with pytest.raises(TachibanaError) as exhausted:
        lifecycle.run(threading.Event())
    assert exhausted.value.classification == ErrorClass.EVENT_RECONNECT_EXHAUSTED
    # CONNECT failures skip the drain wait; one 5 s reconnect backoff, then
    # the daily budget is exhausted.  Still the same session.
    assert delays == [5.0]
    assert progress.snapshot().reconnects_scheduled == 1
    assert progress.snapshot().transport_unreachable_waits == 0
    assert session.state == SessionState.AVAILABLE


def test_event_drain_wait_precedes_same_session_reconnect_and_backoff_grows(tmp_path):
    session, _, _ = _authenticated_session(
        tmp_path, websocket_enabled=True, max_event_reconnects_per_day=5,
    )
    connector = ScriptedEventConnector([(), (), (), (), (), ()])
    delays = []
    lifecycle = TachibanaEventLifecycle(
        session, EventSubscription(("6501",)),
        TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30),
        connector=connector, clock=lambda: NOW, random_value=lambda: 0.0,
        waiter=lambda _stop, delay: delays.append(delay) or False,
        reachability_probe=lambda endpoint: True,
    )
    with pytest.raises(TachibanaError) as exhausted:
        lifecycle.run(threading.Event())
    assert exhausted.value.classification == ErrorClass.EVENT_RECONNECT_EXHAUSTED
    # drain, backoff pairs: 5|5, 5|10, 5|20, 5|40, 5|60(cap), then a final
    # drain before the budget check reports exhaustion.
    assert delays == [5.0, 5.0, 5.0, 10.0, 5.0, 20.0, 5.0, 40.0, 5.0, 60.0, 5.0]
    assert sum(delays) > 60          # the budget can no longer vanish in seconds
    assert session.state == SessionState.AVAILABLE   # never re-authenticated
    assert len(connector.calls) == 6


def test_default_reachability_probe_uses_host_only_and_fails_closed(monkeypatch):
    import argus_providers.tachibana.event_stream as stream
    seen = []

    class _Sock:
        def __enter__(self): return self
        def __exit__(self, *exc): return False
    monkeypatch.setattr(stream.socket, "create_connection",
                        lambda address, timeout: seen.append((address, timeout)) or _Sock())
    assert stream._default_reachability("wss://event.example.test/e_api_v4r10/SECRET-PATH/") is True
    assert seen == [(("event.example.test", 443), 3.0)]
    assert "SECRET" not in str(seen)
    monkeypatch.setattr(stream.socket, "create_connection",
                        lambda address, timeout: (_ for _ in ()).throw(OSError("down")))
    assert stream._default_reachability("wss://event.example.test/x/") is False
    assert stream._default_reachability("not a url") is False


def test_transient_sensor_prunes_size_and_age_and_has_no_persistence_surface():
    sensor = TransientLiveSensor(max_symbols=1, window_size=2, window_seconds=30)
    for offset, price in enumerate(("2000", "2001", "2002")):
        sensor.ingest(normalize_market_price(
            _row(pDPP=price), received_at=NOW + timedelta(seconds=offset),
            market_date=date(2026, 9, 1),
        ))
    assert len(sensor.window("6501", now=NOW + timedelta(seconds=2))) == 2
    assert sensor.window("6501", now=NOW + timedelta(seconds=40)) == ()
    assert sensor.diagnostics(now=NOW + timedelta(seconds=40))["symbolCount"] == 0
    assert not hasattr(sensor, "persist")
    assert not hasattr(sensor, "save")


def test_cross_validation_and_redaction_remain_classified_and_secret_safe():
    observation = normalize_market_price(
        _row(), received_at=NOW, market_date=date(2026, 9, 1),
        market_status=MarketStatus.OPEN, market_date_verified=True,
    )
    mismatches = compare_shadow(
        observation, {"current_price": 2100},
        trusted_timestamp=NOW - timedelta(minutes=2),
    )
    assert mismatches[0].classification == MismatchClass.DELAY_DIFFERENCE
    auth_id = "owner-auth-secret"
    virtual = "https://price-kabuka.e-shiten.jp/e_api_v4r10/price/private-token/"
    pem = "-----BEGIN PRIVATE KEY-----\nPRIVATE-MATERIAL\n-----END PRIVATE KEY-----"
    redacted = redact_structure({
        "sAuthId": auth_id, "private_key": pem, "sUrlPrice": virtual,
        "nested": [f"request failed at {virtual}", auth_id],
    }, (auth_id,))
    rendered = json.dumps(redacted)
    assert auth_id not in rendered
    assert "PRIVATE-MATERIAL" not in rendered
    assert "private-token" not in rendered
    assert rendered.count(REDACTED) >= 4
    assert virtual not in redact_text(RuntimeError(f"failed {virtual}"))
    query = f"https://example.invalid/auth?sAuthId={auth_id}&mode=login"
    redacted_query = redact_text(query, (auth_id,))
    assert auth_id not in redacted_query
    assert REDACTED in redacted_query


@pytest.mark.parametrize("hour, minute, phase, status", [
    (7, 59, JapanCashPhase.CLOSED, MarketStatus.CLOSED),
    (8, 0, JapanCashPhase.PREOPEN, MarketStatus.CLOSED),
    (8, 59, JapanCashPhase.PREOPEN, MarketStatus.CLOSED),
    (9, 0, JapanCashPhase.OPEN, MarketStatus.OPEN),
    (11, 30, JapanCashPhase.LUNCH_CLOSED_INTERVAL, MarketStatus.CLOSED),
    (12, 5, JapanCashPhase.AFTERNOON_PREOPEN, MarketStatus.CLOSED),
    (12, 30, JapanCashPhase.AFTERNOON_OPEN, MarketStatus.OPEN),
    (15, 30, JapanCashPhase.CLOSED, MarketStatus.CLOSED),
])
def test_session_truth_uses_canonical_jpx_boundaries(
    hour, minute, phase, status
):
    provider = datetime(
        2026, 9, 2, hour, minute, 5, tzinfo=ZoneInfo("Asia/Tokyo")
    )
    session_truth = resolve_jp_cash_session(
        now=provider.astimezone(timezone.utc),
        provider_time=provider,
        provider_calendar_date=date(2026, 9, 2),
    )
    assert session_truth.phase == phase
    assert session_truth.market_status == status
    assert session_truth.market_date == date(2026, 9, 2)
    assert session_truth.market_date_verified is True
    assert session_truth.session_truth_confident is True
    assert session_truth.calendar_version == "cal-2026.2"


def test_session_truth_rejects_prior_day_clock_skew_and_provider_conflict():
    now = datetime(2026, 9, 2, 0, 30, tzinfo=timezone.utc)
    prior = datetime(2026, 9, 1, 0, 30, tzinfo=timezone.utc)
    stale = resolve_jp_cash_session(
        now=now, provider_time=prior,
        provider_calendar_date=date(2026, 9, 2),
    )
    assert stale.phase == JapanCashPhase.UNKNOWN
    assert stale.market_status == MarketStatus.UNKNOWN
    assert stale.market_date_verified is False

    closed = resolve_jp_cash_session(
        now=now,
        provider_time=now,
        provider_calendar_date=date(2026, 9, 2),
        provider_market_status=MarketStatus.CLOSED,
    )
    assert closed.phase == JapanCashPhase.UNKNOWN
    assert closed.market_status == MarketStatus.UNKNOWN
    assert closed.market_date_verified is True
    assert closed.session_truth_confident is False

    maintenance = resolve_jp_cash_session(
        now=now,
        provider_time=now,
        provider_calendar_date=date(2026, 9, 2),
        provider_health=ProviderHealth.MAINTENANCE,
    )
    assert maintenance.phase == JapanCashPhase.MAINTENANCE
    assert maintenance.market_status == MarketStatus.MAINTENANCE
    assert maintenance.market_date_verified is True
    assert maintenance.session_truth_confident is True

    lunch_now = datetime(2026, 9, 2, 2, 35, tzinfo=timezone.utc)
    lunch = resolve_jp_cash_session(
        now=lunch_now,
        provider_time=lunch_now,
        provider_calendar_date=date(2026, 9, 2),
        provider_health=ProviderHealth.AVAILABLE,
        provider_market_status=MarketStatus.CLOSED,
    )
    assert lunch.phase == JapanCashPhase.LUNCH_CLOSED_INTERVAL
    assert lunch.market_status == MarketStatus.CLOSED
    assert lunch.market_date_verified is True


def test_provider_calendar_packet_and_trading_date_are_independent_on_weekend():
    now = datetime(2026, 9, 5, 0, 0, 5, tzinfo=timezone.utc)
    resolved = resolve_jp_cash_session(
        now=now,
        provider_time=now,
        provider_calendar_date=date(2026, 9, 5),
    )
    assert resolved.provider_calendar_current is True
    assert resolved.event_packet_current is True
    assert resolved.is_trading_day is False
    assert resolved.market_date_verified is False
    assert resolved.session_truth_confident is False
    assert resolved.phase == JapanCashPhase.CLOSED

    packet_current = normalize_market_price(
        _row(**{"tDPP:T": ""}),
        received_at=now,
        market_date=date(2026, 9, 5),
        market_status=MarketStatus.CLOSED,
        market_date_verified=False,
        market_data_timestamp=now,
        market_data_date_verified=True,
        endpoint_category="EVENT",
    )
    assert packet_current.freshness == Freshness.FRESH
    assert packet_current.source_timestamp is None

    holiday_now = datetime(2026, 9, 21, 0, 0, 5, tzinfo=timezone.utc)
    holiday = resolve_jp_cash_session(
        now=holiday_now,
        provider_time=holiday_now,
        provider_calendar_date=date(2026, 9, 21),
    )
    assert holiday.provider_calendar_current is True
    assert holiday.event_packet_current is True
    assert holiday.is_trading_day is False
    assert holiday.market_date_verified is False
    assert holiday.session_truth_confident is False
    assert holiday.phase == JapanCashPhase.CLOSED


def test_preopen_current_board_does_not_relabel_previous_execution():
    now = datetime(2026, 9, 1, 23, 30, 5, tzinfo=timezone.utc)
    observation = normalize_market_price(
        _row(**{"tDPP:T": "15:30"}),
        received_at=now,
        market_date=date(2026, 9, 2),
        market_status=MarketStatus.CLOSED,
        market_date_verified=False,
        market_data_timestamp=now,
        market_data_date_verified=True,
        endpoint_category="EVENT",
    )
    assert observation.freshness == Freshness.FRESH
    assert observation.market_data_timestamp == now
    assert observation.source_timestamp is None
    assert to_canonical_observations(observation)[0]["observedAt"] is None


def test_new_provider_day_does_not_admit_previous_day_status_replay():
    tracker = EventStatusTracker(provider_calendar_date=date(2026, 9, 3))
    old = tracker.apply(parse_event_frame(_ss_frame(
        1, 1, provider_time="20260902235959",
        login_permission="0", system_status="1",
    )))
    assert old.status_date_verified is False
    assert old.provider_health == ProviderHealth.AVAILABLE
    current = tracker.apply(parse_event_frame(_ss_frame(
        2, 2, provider_time="20260903053000",
        login_permission="1", system_status="1",
    )))
    assert current.status_date_verified is True
    assert current.provider_health == ProviderHealth.AVAILABLE


def test_provider_datetime_parser_is_exact_and_timezone_aware():
    parsed = parse_provider_datetime("2026.09.02-09:00:05.123")
    assert parsed == datetime(2026, 9, 2, 0, 0, 5, 123000, tzinfo=timezone.utc)
    assert parse_provider_datetime("2026-09-02T09:00:05+09:00") is None


def test_host_singleton_is_exclusive_empty_and_recovery_isolated(tmp_path):
    path = tmp_path / "tachibana-live-sensor.lock"
    first = ProcessSingletonLease(path)
    second = ProcessSingletonLease(path)
    first.acquire()
    assert first.acquired is True
    assert path.read_bytes() == b""
    assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(SingletonLeaseError, match="singleton_held"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()
    with pytest.raises(SingletonLeaseError, match="recovery_filesystem"):
        ProcessSingletonLease(Path("/var/data/tachibana.lock"))


def test_event_progress_is_thread_safe_value_free_and_proves_advancement():
    progress = EventLifecycleProgress()
    first = datetime(2026, 9, 2, 0, 0, 5, tzinfo=timezone.utc)
    second = first + timedelta(seconds=5)
    progress.connection_started()
    progress.frame_received(
        sequence=1, provider_timestamp=first, received_at=first,
        command="SS",
    )
    progress.reconnect_scheduled()
    progress.observations_ingested(3)
    progress.frame_received(
        sequence=2, provider_timestamp=second, received_at=second,
        command="ST", status_code="1",
    )
    progress.failure_observed(
        classification=ErrorClass.PROVIDER,
        detail="EVENT_STATUS_ERROR_INVALID",
        stage="STATUS",
    )
    snapshot = progress.snapshot()
    assert snapshot.connections_started == 1
    assert snapshot.reconnects_scheduled == 1
    assert snapshot.frames_received == 2
    assert snapshot.observations_ingested == 3
    assert snapshot.first_sequence == 1
    assert snapshot.last_sequence == 2
    assert snapshot.first_provider_timestamp == first
    assert snapshot.last_provider_timestamp == second
    assert snapshot.last_command == "ST"
    assert snapshot.last_status_code == "1"
    assert snapshot.last_failure_classification == "PROVIDER"
    assert snapshot.last_failure_detail == "EVENT_STATUS_ERROR_INVALID"
    assert snapshot.last_failure_stage == "STATUS"
    assert snapshot.subscription_state == "CONTROL_ACTIVE"
    assert snapshot.ss_frames == 1
    assert snapshot.st_frames == 1
    assert snapshot.sequence_advanced is True
    assert snapshot.provider_timestamp_advanced is True
    assert not hasattr(snapshot, "raw_frame")
    assert not hasattr(snapshot, "market_values")

    progress.frame_received(
        sequence=3, provider_timestamp=second + timedelta(seconds=5),
        received_at=second + timedelta(seconds=5), command="FD", fd_rows=1,
    )
    progress.frame_received(
        sequence=4, provider_timestamp=second + timedelta(seconds=10),
        received_at=second + timedelta(seconds=10), command="KP",
    )
    assert progress.snapshot().subscription_state == "FD_ACTIVE"


def test_event_progression_is_connection_local_across_reconnects():
    progress = EventLifecycleProgress()
    first = datetime(2026, 9, 2, 0, 0, 5, tzinfo=timezone.utc)
    progress.connection_started()
    progress.frame_received(
        sequence=1, provider_timestamp=first, received_at=first,
        command="KP",
    )
    progress.connection_started()
    later = first + timedelta(seconds=10)
    progress.frame_received(
        sequence=1, provider_timestamp=later, received_at=later,
        command="KP",
    )
    snapshot = progress.snapshot()
    assert snapshot.frames_received == 2
    assert snapshot.first_provider_timestamp < snapshot.last_provider_timestamp
    assert snapshot.current_connection_first_sequence == 1
    assert snapshot.current_connection_last_sequence == 1
    assert snapshot.sequence_advanced is False
    assert snapshot.provider_timestamp_advanced is False


def test_live_runtime_flags_are_exact_and_symbol_bound_is_three():
    valid = TachibanaConfig(
        enabled=True, shadow_only=True, authoritative=False,
        websocket_enabled=True, max_symbols=3,
    )
    validate_live_flags(valid)
    for invalid in (
        replace(valid, enabled=False),
        replace(valid, websocket_enabled=False),
        replace(valid, max_symbols=4),
    ):
        with pytest.raises(TachibanaError) as failure:
            validate_live_flags(invalid)
        assert failure.value.classification == ErrorClass.CONFIGURATION


class _ReferenceResponse:
    def __init__(self, payload, *, ok=True):
        self._payload = payload
        self.ok = ok

    def json(self):
        return self._payload


def _current_observation(symbol: str, now: datetime, price: str, volume: str):
    return normalize_market_price(
        _row(
            sIssueCode=symbol,
            pDPP=price,
            pDV=volume,
            **{"tDPP:T": now.astimezone(ZoneInfo("Asia/Tokyo")).strftime("%H:%M:%S")},
        ),
        received_at=now,
        market_date=now.astimezone(ZoneInfo("Asia/Tokyo")).date(),
        market_status=MarketStatus.OPEN,
        market_date_verified=True,
    )


def test_operational_cross_validation_requires_current_explicitly_live_rows():
    now = datetime(2026, 9, 2, 0, 1, 10, tzinfo=timezone.utc)
    observations = {
        symbol: _current_observation(symbol, now, "2000", "100000")
        for symbol in ("8058", "9984", "5803")
    }
    rows = [{
        "symbol": symbol,
        "status": "live",
        "realtimeEvidence": True,
        "sourceTimestamp": now.isoformat(),
        "price": 2000,
        "volume": 100000,
    } for symbol in observations]
    result = cross_validate_current(
        observations,
        now=now,
        fetch=lambda *_args, **_kwargs: _ReferenceResponse({
            "status": "live", "stocks": rows,
        }),
        session_phase=JapanCashPhase.OPEN,
    )
    assert result.acceptable is True
    assert result.classification == "ACCEPTABLE"
    assert result.compared_symbol_count == 3
    assert result.comparable_field_count == 6

    delayed = [dict(row, realtimeEvidence=False) for row in rows]
    rejected = cross_validate_current(
        observations,
        now=now,
        fetch=lambda *_args, **_kwargs: _ReferenceResponse({
            "status": "live", "stocks": delayed,
        }),
        session_phase=JapanCashPhase.OPEN,
    )
    assert rejected.classification == "INSUFFICIENT_CURRENT_COVERAGE"
    assert rejected.acceptable is False


def test_board_cross_validation_is_eligible_in_preopen_without_execution_time():
    now = datetime(2026, 9, 1, 23, 30, 10, tzinfo=timezone.utc)
    observation = normalize_market_price(
        _row(**{"tDPP:T": ""}),
        received_at=now,
        market_date=date(2026, 9, 2),
        market_status=MarketStatus.CLOSED,
        market_date_verified=False,
        market_data_timestamp=now,
        market_data_date_verified=True,
        endpoint_category="EVENT",
    )
    payload = {
        "status": "live",
        "stocks": [{
            "symbol": "6501",
            "status": "live",
            "realtimeEvidence": True,
            "sourceTimestamp": now.isoformat(),
            "bestAsk": 2001,
            "bestBid": 2000,
        }],
    }
    board = cross_validate_current(
        {"6501": observation},
        now=now,
        fetch=lambda *_args, **_kwargs: _ReferenceResponse(payload),
        scope="BOARD",
        session_phase=JapanCashPhase.PREOPEN,
    )
    assert board.acceptable is True
    assert board.scope == "BOARD"
    assert board.compared_symbol_count == 1
    assert board.comparable_field_count == 2

    lunch = cross_validate_current(
        {"6501": observation},
        now=now,
        fetch=lambda *_args, **_kwargs: pytest.fail(
            "ineligible board scope must not query the reference provider"
        ),
        scope="BOARD",
        session_phase=JapanCashPhase.LUNCH_CLOSED_INTERVAL,
    )
    assert lunch.classification == "SESSION_NOT_ELIGIBLE"

    execution = cross_validate_current(
        {"6501": observation},
        now=now,
        fetch=lambda *_args, **_kwargs: _ReferenceResponse(payload),
        scope="EXECUTION",
        session_phase=JapanCashPhase.PREOPEN,
    )
    assert execution.acceptable is False
    assert execution.classification == "SESSION_NOT_ELIGIBLE"


def test_live_acceptance_requires_event_and_market_progression(tmp_path):
    now = [datetime(2026, 9, 1, 23, 0, 10, tzinfo=timezone.utc)]
    config = TachibanaConfig(
        enabled=True, shadow_only=True, authoritative=False,
        websocket_enabled=True, max_symbols=3,
        auth_id_path=tmp_path / "auth", private_key_path=tmp_path / "key",
    )
    symbols = ("8058", "9984", "5803")
    rows = [{
        "symbol": symbol,
        "status": "live",
        "realtimeEvidence": True,
        "sourceTimestamp": datetime(
            2026, 9, 2, 0, 1, 15, tzinfo=timezone.utc
        ).isoformat(),
        "price": 2001,
        "volume": 100100,
    } for symbol in symbols]
    runtime = TachibanaLiveRuntime(
        config,
        symbols=symbols,
        clock=lambda: now[0],
        reference_fetch=lambda *_args, **_kwargs: _ReferenceResponse({
            "status": "live", "stocks": rows,
        }),
    )
    runtime._authenticated = True
    runtime._provider_calendar_date = date(2026, 9, 2)
    runtime.session.diagnostics.health = ProviderHealth.AVAILABLE
    runtime.session.diagnostics.websocket_connected = True
    first = now[0]
    runtime.progress.connection_started()
    runtime.progress.frame_received(
        sequence=1, provider_timestamp=first, received_at=first,
    )
    for symbol in symbols:
        runtime.sensor.ingest(normalize_market_price(
            _row(
                sIssueCode=symbol,
                pQAP="2002", pQBP="1999", pAV="1000", pBV="1100",
                **{"tDPP:T": ""},
            ),
            received_at=first,
            market_date=date(2026, 9, 2),
            market_status=MarketStatus.CLOSED,
            market_date_verified=False,
            market_data_timestamp=first,
            market_data_date_verified=True,
            endpoint_category="EVENT",
        ))
    assert runtime.acceptance_snapshot().preopen_book_live is False

    now[0] += timedelta(seconds=5)
    runtime.progress.frame_received(
        sequence=2, provider_timestamp=now[0], received_at=now[0],
    )
    for symbol in symbols:
        runtime.sensor.ingest(normalize_market_price(
            _row(
                sIssueCode=symbol,
                pQAP="2001", pQBP="2000", pAV="1200", pBV="1300",
                **{"tDPP:T": ""},
            ),
            received_at=now[0],
            market_date=date(2026, 9, 2),
            market_status=MarketStatus.CLOSED,
            market_date_verified=False,
            market_data_timestamp=now[0],
            market_data_date_verified=True,
            endpoint_category="EVENT",
        ))
    preopen = runtime.acceptance_snapshot()
    assert preopen.preopen_book_live is True
    assert preopen.execution_market_live is False
    assert preopen.transition_window == "MORNING"
    assert preopen.classification == "PREOPEN_BOOK_LIVE"

    now[0] = datetime(2026, 9, 2, 0, 1, 10, tzinfo=timezone.utc)
    runtime.progress.frame_received(
        sequence=3, provider_timestamp=now[0], received_at=now[0],
    )
    for symbol in symbols:
        runtime.sensor.ingest(_current_observation(
            symbol, now[0], "2000", "100000"
        ))
        runtime.progress.observations_ingested(3)
    assert runtime.acceptance_snapshot().execution_market_live is False

    now[0] += timedelta(seconds=5)
    runtime.progress.frame_received(
        sequence=4, provider_timestamp=now[0], received_at=now[0],
    )
    for symbol in symbols:
        runtime.sensor.ingest(_current_observation(
            symbol, now[0], "2001", "100100"
        ))
    accepted = runtime.acceptance_snapshot(cross_validate=True)
    assert accepted.accepted is True
    assert accepted.classification == "ACCEPTED"
    assert accepted.event_sequence_advanced is True
    assert accepted.event_timestamp_advanced is True
    assert accepted.event_connections_started == 1
    assert accepted.event_reconnects_scheduled == 0
    assert accepted.event_last_failure_classification is None
    assert accepted.event_last_failure_detail is None
    assert accepted.source_timestamp_advanced is True
    assert accepted.market_value_changed is True
    assert accepted.book_progression is True
    assert accepted.execution_progression is True
    assert accepted.preopen_book_live is True
    assert accepted.execution_market_live is True
    assert accepted.price_current_count == 3
    assert accepted.cross_validation.acceptable is True


def test_runtime_keeps_date_and_price_initial_read_boundaries_separate(
    tmp_path, monkeypatch,
):
    config = TachibanaConfig(
        enabled=True, shadow_only=True, authoritative=False,
        websocket_enabled=True, max_symbols=3,
        auth_id_path=tmp_path / "auth", private_key_path=tmp_path / "key",
    )
    runtime = TachibanaLiveRuntime(config, symbols=("6501",))
    monkeypatch.setattr(runtime.session, "authenticate", lambda: None)
    monkeypatch.setattr(runtime, "stop", lambda: True)

    class DateFailureClient:
        def __init__(self, _session):
            self.last_read_diagnostic = ProviderReadDiagnostic(
                operation="CLMStkGetDateZyouhou",
                endpoint_class="MASTER",
                stage="PROVIDER_DATE_RESPONSE_CLMID",
                classification="PROVIDER",
                expected_response_clmid="CLMDateZyouhou",
                observed_response_clmid="CLMUnknownDateResponse",
                schema_failure_token="CLMID_MISMATCH",
            )

        def provider_calendar_date(self):
            raise TachibanaError(ErrorClass.PROVIDER)

        def market_price(self, *_args):
            pytest.fail("PRICE must not start after Date contract failure")

    monkeypatch.setattr(
        tachibana_runtime, "TachibanaReadOnlyClient", DateFailureClient
    )
    with pytest.raises(TachibanaError):
        runtime.start()
    diagnostics = runtime.initial_read_diagnostics_safe_dict()
    assert diagnostics["providerDate"]["stage"] == (
        "PROVIDER_DATE_RESPONSE_CLMID"
    )
    assert diagnostics["priceBaseline"]["stage"] == "NOT_STARTED"
    assert diagnostics["priceBaseline"]["classification"] == "NOT_ATTEMPTED"


def test_price_baseline_normalization_failure_has_safe_distinct_stage(
    tmp_path, monkeypatch,
):
    response = _success(
        "CLMMfdsGetMarketPrice", "aCLMMfdsMarketPrice",
        [{"sIssueCode": "6501", "pDPP": "2000"}],
    )
    response["p_rv_date"] = "2026.09.01-15:00:10.000"
    session, _, _ = _authenticated_session(tmp_path, [response])
    client = TachibanaReadOnlyClient(session)
    config = replace(
        session.config,
        shadow_only=True,
        authoritative=False,
        websocket_enabled=True,
        max_symbols=3,
    )
    runtime = TachibanaLiveRuntime(config, symbols=("6501",), clock=lambda: NOW)
    runtime._provider_calendar_date = date(2026, 9, 1)
    monkeypatch.setattr(
        tachibana_runtime,
        "normalize_market_price",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TachibanaError(ErrorClass.NORMALIZATION)
        ),
    )
    with pytest.raises(TachibanaError) as caught:
        runtime._read_price_snapshot(client)
    assert caught.value.classification == ErrorClass.NORMALIZATION
    assert client.read_diagnostic_safe_dict()["stage"] == (
        "PRICE_BASELINE_NORMALIZE"
    )
    assert client.read_diagnostic_safe_dict()["schemaFailureToken"] == (
        "NORMALIZATION_REJECTED"
    )


def test_afternoon_preopen_to_open_is_valid_transition_fallback(tmp_path):
    now = [datetime(2026, 9, 2, 3, 5, 10, tzinfo=timezone.utc)]
    symbol = "8058"
    config = TachibanaConfig(
        enabled=True, shadow_only=True, authoritative=False,
        websocket_enabled=True, max_symbols=3,
        auth_id_path=tmp_path / "auth", private_key_path=tmp_path / "key",
    )
    reference_time = datetime(
        2026, 9, 2, 3, 30, 15, tzinfo=timezone.utc
    )
    runtime = TachibanaLiveRuntime(
        config,
        symbols=(symbol,),
        clock=lambda: now[0],
        reference_fetch=lambda *_args, **_kwargs: _ReferenceResponse({
            "status": "live",
            "stocks": [{
                "symbol": symbol,
                "status": "live",
                "realtimeEvidence": True,
                "sourceTimestamp": reference_time.isoformat(),
                "price": 2001,
                "volume": 100100,
            }],
        }),
    )
    runtime._authenticated = True
    runtime._provider_calendar_date = date(2026, 9, 2)
    runtime.session.diagnostics.health = ProviderHealth.AVAILABLE
    runtime.session.diagnostics.websocket_connected = True
    runtime.progress.connection_started()
    runtime.progress.frame_received(
        sequence=1, provider_timestamp=now[0], received_at=now[0],
    )
    runtime.sensor.ingest(normalize_market_price(
        _row(
            sIssueCode=symbol,
            pQAP="2002", pQBP="1999", pAV="1000", pBV="1100",
            **{"tDPP:T": ""},
        ),
        received_at=now[0], market_date=date(2026, 9, 2),
        market_status=MarketStatus.CLOSED, market_date_verified=False,
        market_data_timestamp=now[0], market_data_date_verified=True,
        endpoint_category="EVENT",
    ))
    assert runtime.acceptance_snapshot().preopen_book_live is False

    now[0] += timedelta(seconds=5)
    runtime.progress.frame_received(
        sequence=2, provider_timestamp=now[0], received_at=now[0],
    )
    runtime.sensor.ingest(normalize_market_price(
        _row(
            sIssueCode=symbol,
            pQAP="2001", pQBP="2000", pAV="1200", pBV="1300",
            **{"tDPP:T": ""},
        ),
        received_at=now[0], market_date=date(2026, 9, 2),
        market_status=MarketStatus.CLOSED, market_date_verified=False,
        market_data_timestamp=now[0], market_data_date_verified=True,
        endpoint_category="EVENT",
    ))
    preopen = runtime.acceptance_snapshot()
    assert preopen.preopen_book_live is True
    assert preopen.transition_window == "AFTERNOON"

    now[0] = datetime(2026, 9, 2, 3, 30, 10, tzinfo=timezone.utc)
    runtime.progress.frame_received(
        sequence=3, provider_timestamp=now[0], received_at=now[0],
    )
    runtime.sensor.ingest(_current_observation(
        symbol, now[0], "2000", "100000"
    ))
    assert runtime.acceptance_snapshot().execution_market_live is False

    now[0] += timedelta(seconds=5)
    runtime.progress.frame_received(
        sequence=4, provider_timestamp=now[0], received_at=now[0],
    )
    runtime.sensor.ingest(_current_observation(
        symbol, now[0], "2001", "100100"
    ))
    accepted = runtime.acceptance_snapshot(cross_validate=True)
    assert accepted.accepted is True
    assert accepted.preopen_book_live is True
    assert accepted.execution_market_live is True
    assert accepted.transition_window == "AFTERNOON"


def test_service_starts_only_in_live_sensor_window_and_reauth_is_rolling():
    tokyo = ZoneInfo("Asia/Tokyo")
    before = datetime(2026, 9, 2, 5, 35, tzinfo=tokyo)
    assert _scheduled_sensor_start(now=before) == datetime(
        2026, 9, 2, 7, 55, tzinfo=tokyo
    )
    available = datetime(2026, 9, 2, 9, 0, tzinfo=tokyo)
    assert _scheduled_sensor_start(now=available) is None
    assert _scheduled_sensor_start(
        now=available, force_next_trading_day=True
    ) == datetime(2026, 9, 3, 7, 55, tzinfo=tokyo)

    attempts: deque[float] = deque()
    assert _consume_reauthentication_budget(attempts, now=0.0) is True
    assert _consume_reauthentication_budget(attempts, now=30.0) is True
    assert _consume_reauthentication_budget(attempts, now=60.0) is False
    assert _consume_reauthentication_budget(attempts, now=901.0) is True


def test_acceptance_guard_never_consumes_auth_before_live_preopen():
    tokyo = ZoneInfo("Asia/Tokyo")
    assert _live_start_guard(datetime(
        2026, 9, 2, 7, 54, 59, tzinfo=tokyo
    )) == "LIVE_START_GUARD_BEFORE_0755"
    assert _live_start_guard(datetime(
        2026, 9, 2, 7, 55, 0, tzinfo=tokyo
    )) is None
    assert _live_start_guard(datetime(
        2026, 9, 2, 9, 0, 0, tzinfo=tokyo
    )) == "WAIT_FOR_AFTERNOON_PREOPEN"
    assert _live_start_guard(datetime(
        2026, 9, 2, 12, 0, 0, tzinfo=tokyo
    )) is None
    assert _live_start_guard(datetime(
        2026, 9, 2, 12, 30, 0, tzinfo=tokyo
    )) == "PREOPEN_START_WINDOWS_MISSED"


def test_live_canary_classifies_competing_singleton_without_runtime_start(
    monkeypatch, capsys,
):
    class HeldLease:
        def __init__(self, _path):
            pass

        def __enter__(self):
            raise SingletonLeaseError("singleton_held")

        def __exit__(self, *_args):
            return False

    runtime_started = False

    class ForbiddenRuntime:
        def __init__(self, *_args, **_kwargs):
            nonlocal runtime_started
            runtime_started = True

    monkeypatch.setattr(live_acceptance, "_live_start_guard", lambda: None)
    monkeypatch.setattr(
        live_acceptance.TachibanaConfig, "from_env", lambda: object()
    )
    monkeypatch.setattr(live_acceptance, "ProcessSingletonLease", HeldLease)
    monkeypatch.setattr(live_acceptance, "TachibanaLiveRuntime", ForbiddenRuntime)

    assert live_acceptance.main() == 2
    output = capsys.readouterr().out.strip()
    assert runtime_started is False
    assert '"classification":"DUPLICATE_ACCEPTANCE_PROCESS"' in output
    assert '"authDiagnostic":null' in output
    assert '"singletonAcquired":false' in output


def test_live_canary_outputs_safe_auth_boundary_without_response_text(
    monkeypatch, capsys,
):
    class NullLease:
        def __init__(self, _path):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeSession:
        auth_diagnostic = AuthDiagnostic(
            classification="AUTH_SERVER_REJECTED_990006",
            boundary="SERVER_AUTH_REJECTED",
            http_status=200,
            response_clmid="CLMAuthLoginAck",
            result_code="990006",
            official_reason="SYSTEM_LOGIN_FAILED",
            response_matched_ack=True,
            encrypted_virtual_urls_present=False,
        )

    class FakeRuntime:
        def __init__(self, *_args, **_kwargs):
            self.session = FakeSession()

        def start(self):
            raise TachibanaError(ErrorClass.AUTH_SERVER_REJECTED)

        def stop(self):
            return True

        def initial_read_diagnostics_safe_dict(self):
            return {
                "providerDate": ProviderReadDiagnostic(
                    operation="CLMStkGetDateZyouhou",
                    endpoint_class="MASTER",
                    expected_response_clmid="CLMDateZyouhou",
                ).safe_dict(),
                "priceBaseline": ProviderReadDiagnostic(
                    operation="CLMMfdsGetMarketPrice",
                    endpoint_class="PRICE",
                    expected_response_clmid="CLMMfdsGetMarketPrice",
                ).safe_dict(),
            }

    monkeypatch.setattr(live_acceptance, "_live_start_guard", lambda: None)
    monkeypatch.setattr(live_acceptance, "ProcessSingletonLease", NullLease)
    monkeypatch.setattr(live_acceptance, "TachibanaLiveRuntime", FakeRuntime)
    assert live_acceptance.main() == 2
    output = capsys.readouterr().out.strip()
    assert "AUTH_SERVER_REJECTED_990006" in output
    assert '\"httpStatus\":200' in output
    assert '\"sCLMID\":\"CLMAuthLoginAck\"' in output
    assert '\"sResultCode\":\"990006\"' in output
    assert '\"initialReads\":{' in output
    assert '\"providerDate\":{' in output
    assert '\"priceBaseline\":{' in output
    assert "sResultText" not in output


def test_live_canary_classifies_post_auth_failure_by_exact_initial_read_stage():
    class FakeRuntime:
        def initial_read_diagnostics_safe_dict(self):
            return {
                "providerDate": ProviderReadDiagnostic(
                    operation="CLMStkGetDateZyouhou",
                    endpoint_class="MASTER",
                    stage="PROVIDER_DATE_VALUE",
                    classification="PROVIDER",
                    expected_response_clmid="CLMDateZyouhou",
                    observed_response_clmid="CLMDateZyouhou",
                    schema_failure_token="CURRENT_DATE_INVALID",
                ).safe_dict(),
                "priceBaseline": ProviderReadDiagnostic(
                    operation="CLMMfdsGetMarketPrice",
                    endpoint_class="PRICE",
                    expected_response_clmid="CLMMfdsGetMarketPrice",
                ).safe_dict(),
            }

    assert live_acceptance._initial_read_failure(FakeRuntime()) == (
        "PROVIDER_DATE_VALUE"
    )
