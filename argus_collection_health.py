"""Read-only collection metadata for the existing authenticated diagnostics.

No provider IO, source payload, identifier, error text, or decision authority.
A successful poll and a changed dataset are deliberately different clocks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Mapping

SOURCE_SPECS = {
    "credit_balances": ("JPX信用残", "公式週次公表", 14 * 86400),
    "credit_valuation": ("信用評価損益率", "公式週次公表", 14 * 86400),
    "future_map": ("参考予測", "更新通知・朝6時の補完", 3 * 86400),
    "morning_map": ("朝の価格目盛り", "取引日の寄付前", 4 * 86400),
    "feature_history": ("分析に使う履歴", "取得済み入力の変更時", 4 * 86400),
    "news_collection": ("ニュース収集", "既存の定期巡回", 3 * 3600),
}
WINDOW_LIMIT = 3000
WINDOW_SOURCES = {"vix": "VIX", "topix": "TOPIX", "us10y": "米10年金利", "usdjpy": "ドル円"}


def _stamp(value, now):
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None and parsed <= now else None
    except (ValueError, TypeError):
        return None


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None


def _count(value):
    return value if type(value) is int and 0 <= value <= 9_007_199_254_740_991 else None


def build_collection_health(inputs, *, now_iso):
    """Only reviewed scalar fields survive. Unknown never becomes healthy."""
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    if now.tzinfo is None:
        raise ValueError("collection_health_timezone_required")
    now = now.astimezone(timezone.utc)
    inputs = inputs if isinstance(inputs, Mapping) else {}
    sources = inputs.get("sources") if isinstance(inputs.get("sources"), Mapping) else {}
    rows = []
    for key, (label, cadence, stale_after) in SOURCE_SPECS.items():
        raw = sources.get(key) if isinstance(sources.get(key), Mapping) else {}
        changed, checked = (_stamp(raw.get(field), now) for field in ("dataUpdatedAt", "lastCheckedAt"))
        period = _day(raw.get("latestPeriod"))
        period_clock = _stamp(period + "T00:00:00+09:00", now) if period else None
        weekly = key in ("credit_balances", "credit_valuation")
        basis = period_clock if weekly else changed
        age = int((now - basis).total_seconds()) if basis else None
        status = "failed" if raw.get("failed") is True else (
            "unknown" if changed is None or basis is None else "stale" if age >= stale_after else "current")
        # The data clock is not advanced by the receipt/check clock.
        rows.append({"key": key, "labelJa": label, "expectedCadenceJa": cadence,
                     "dataUpdatedAt": changed.isoformat() if changed else None,
                     "lastCheckedAt": checked.isoformat() if checked else None,
                     "latestPeriod": period, "rowCount": _count(raw.get("rowCount")),
                     "dataAgeSec": age, "staleAfterSec": stale_after, "status": status,
                     "freshnessBasis": "period_end" if weekly else "data_update"})
    spans = inputs.get("inputSpans") if isinstance(inputs.get("inputSpans"), Mapping) else {}
    windows = []
    for key, label in WINDOW_SOURCES.items():
        span = spans.get("price_series:" + key)
        span = span if isinstance(span, Mapping) else {}
        count = _count(span.get("rows"))
        windows.append({"key": key, "labelJa": label, "rows": count, "limit": WINDOW_LIMIT,
                        "warningAt": WINDOW_LIMIT * 4 // 5,
                        "status": "unknown" if count is None else "warning" if count >= WINDOW_LIMIT * 4 // 5 else "within_limit",
                        "scope": "calculation_window", "archiveRowsMeasured": False})
    policy = inputs.get("namingPolicy")
    return {"schemaVersion": "argus-collection-health-v1", "asOf": now_iso,
            "sources": rows, "inputWindows": windows,
            "namingPolicy": policy if policy in ("configured_valid", "not_configured", "invalid") else "unknown",
            "noteJa": "データ更新と確認時刻は別です。窓の上限は分析対象で、原本の保存件数ではありません。",
            "actionAuthority": False}
