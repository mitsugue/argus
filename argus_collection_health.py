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
from argus_archive_health import TABLES as ARCHIVE_TABLES
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
    from argus_credit_publication import weekly_expectation
    credit_schedule = weekly_expectation(now)
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
        if weekly:
            expected = credit_schedule["latestDuePeriod"]
            rows[-1].update({
                "expectedLatestPeriod": expected,
                "scheduledPublicationAt": credit_schedule["latestDueAt"],
                "nextScheduledPeriod": credit_schedule["nextPeriod"],
                "nextScheduledPublicationAt": credit_schedule["nextPublicationAt"],
                "publicationState": "unknown" if expected is None or (period is not None and period_clock is None) else
                    "overdue" if period is None or period < expected else "current",
                "publicationBasis": "nominal_schedule_not_actual_receipt",
            })
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
    raw_archives = inputs.get("archives") if isinstance(inputs.get("archives"), Mapping) else {}
    archives = []
    for key, names in ARCHIVE_TABLES.items():
        raw = raw_archives.get(key) if isinstance(raw_archives.get(key), Mapping) else {}
        raw_tables = raw.get("tables") if isinstance(raw.get("tables"), Mapping) else {}
        tables = []
        for name in names:
            table = raw_tables.get(name) if isinstance(raw_tables.get(name), Mapping) else {}
            count = _count(table.get("rows"))
            measured = table.get("status") == "measured" and count is not None
            tables.append({"key": name, "status": "measured" if measured else
                           "not_created" if table.get("status") == "not_created" else "unknown",
                           "rows": count if measured else None})
        status = raw.get("status")
        db_bytes, wal_bytes = _count(raw.get("databaseBytes")), _count(raw.get("walBytes"))
        measured = status == "measured" and db_bytes is not None and wal_bytes is not None
        archives.append({"key": key, "status": "measured" if measured else
                         status if status in ("not_configured", "missing", "unavailable") else "unknown",
                         "databaseBytes": db_bytes if measured else None,
                         "walBytes": wal_bytes if measured else None,
                         "tables": tables if measured else [{**t, "rows": None, "status": "unknown"} for t in tables],
                         "scope": "local_sqlite_archive", "rowLimit": None,
                         "storageQuotaBytes": None, "automaticPruning": False,
                         "remoteRecoveryMeasured": False})
    policy = inputs.get("namingPolicy")
    return {"schemaVersion": "argus-collection-health-v1", "asOf": now_iso,
            "sources": rows, "inputWindows": windows, "archives": archives,
            "namingPolicy": policy if policy in ("configured_valid", "not_configured", "invalid") else "unknown",
            "noteJa": "データ更新と確認時刻は別です。窓の上限は分析対象で、原本の保存件数ではありません。",
            "actionAuthority": False}
