# -*- coding: utf-8 -*-
"""Deterministic SHO Phase 3 presentation and validation helpers.

This module never fetches data and never calls AI.  It turns already-observed,
publication-time-gated facts into an operating sheet.  Missing inputs remain
missing; no fixture or zero substitution is permitted.
"""
from datetime import datetime, timezone
from math import sqrt
from typing import Any, Dict, Iterable, List, Optional, Sequence

SCHEMA_VERSION = "argus-sho-phase3-v1"
METHOD_VERSION = "sho-phase3-2026.07"


SOURCE_OF_TRUTH = [
    ("jp_daily", "J-Quants equities/bars/daily", "前営業日正式値", "daily", "plan-defined", "contracted", "live"),
    ("jp_intraday_tick", "J-Quants minute/tick add-on", "none", "intraday", "provider", "not_contracted", "source_unavailable"),
    ("jp_current_price", "moomoo", "J-Quants previous official close", "session", "realtime", "entitlement", "entitlement_unavailable"),
    ("us_price", "moomoo US", "Twelve Data", "intraday", "provider", "contracted", "live"),
    ("fx", "Twelve Data/FRED", "provider cache", "intraday/daily", "provider", "contracted", "live"),
    ("crypto", "CoinGecko", "Coinbase", "intraday", "provider", "free", "live"),
    ("credit_two_market", "JPX 二市場合計", "admin CSV", "weekly", "publication schedule", "official/free", "manual_csv"),
    ("investor_types", "J-Quants investor-types: TokyoNagoya", "admin CSV", "weekly", "published date", "contracted", "backfill_available"),
    ("nikkei_per_pbr", "Nikkei official licensed import", "none", "daily", "publication timing", "license_unverified", "license_blocked"),
    ("breadth_counts", "J-Quants V2 adjusted daily bars + historical master", "none", "daily", "16:30 provider update / 17:00 available", "contracted", "backfill_available"),
    ("tdnet", "J-Quants TDnet add-on", "JPX TDnet", "event", "near real-time", "contracted", "live"),
    ("edinet", "EDINET API", "official IR", "event", "provider", "official", "live"),
    ("economic_events", "official agencies", "existing event ledger", "event", "source-specific", "official/free", "live"),
]


HEURISTICS = [
    ("credit_short_800b", "二市場信用売り残8,000億円", "sho_heuristic", "CREDIT_THRESHOLD_CROSS"),
    ("nikkei_leverage_ratio_below_1", "1570信用倍率1倍未満", "insufficient_data", None),
    ("ns_ratio", "NS倍率", "insufficient_data", None),
    ("per_21x", "PER21倍", "sho_heuristic", "VALUATION_CEILING_ROLLOVER"),
    ("breadth_120_80", "騰落レシオ120／80", "sho_heuristic", "BREADTH_TURN"),
    ("wall_rejection", "壁ドン", "experimental", "TREND_STRUCTURE_BREAK"),
    ("vix_macd", "VIX MACD", "insufficient_data", None),
    ("good_news_price_down", "好材料なのに下落", "experimental", "REACTION_ANOMALY"),
]


def source_of_truth_matrix(status_overrides: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    overrides = status_overrides or {}
    return [{"dataId": data_id, "primary": primary, "fallback": fallback,
             "frequency": frequency, "delay": delay, "license": license_name,
             "currentStatus": overrides.get(data_id, status)}
            for data_id, primary, fallback, frequency, delay, license_name, status in SOURCE_OF_TRUTH]


def normalize_jquants_investor_rows(rows: Iterable[Dict[str, Any]], now_iso: str,
                                    section: str = "TokyoNagoya") -> List[Dict[str, Any]]:
    """Map official investor-type rows to ledger candidates.

    J-Quants documents all monetary fields in thousand yen.  PubDate is used
    as publication time; 18:00 JST is conservative and prevents weekly data
    from becoming visible at its period end or before official publication.
    """
    fields = {
        "flow.foreign": "FrgnBal", "flow.individual": "IndBal",
        "flow.investment_trust": "InvTrBal", "flow.trust_bank": "TrstBnkBal",
        "flow.proprietary": "PropBal",
    }
    out: List[Dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, dict) or str(raw.get("Section") or "") != section:
            continue
        period = str(raw.get("EnDate") or "")[:10]
        published = str(raw.get("PubDate") or "")[:10]
        if len(period) != 10 or len(published) != 10:
            continue
        available = f"{published}T18:00:00+09:00"
        for series_id, key in fields.items():
            value = raw.get(key)
            if value is None:
                continue
            try:
                yen = float(value) * 1000.0
            except (TypeError, ValueError):
                continue
            out.append({"seriesId": series_id, "periodEnd": period,
                        "publishedAt": available, "availableFrom": available,
                        "observedAt": now_iso, "value": yen, "unit": "JPY",
                        "source": "J-Quants /equities/investor-types TokyoNagoya",
                        "sourceKind": "official", "status": "live",
                        "metadata": {"section": section, "providerUnit": "thousand_yen",
                                     "publicationPolicy": "official_pubdate_18:00_JST"}})
    return out


def _returns(values: Sequence[Dict[str, Any]], start_index: int, horizon: int) -> Optional[float]:
    if start_index + horizon >= len(values):
        return None
    start, end = values[start_index].get("close"), values[start_index + horizon].get("close")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start <= 0:
        return None
    return (float(end) / float(start) - 1.0) * 100.0


def walk_forward_backtest(signals: Iterable[Dict[str, Any]], prices: Iterable[Dict[str, Any]],
                          min_validated_samples: int = 30) -> Dict[str, Any]:
    """Fixed-horizon walk-forward evaluation with publication-time gating."""
    bars = sorted((dict(x) for x in prices if isinstance(x, dict)),
                  key=lambda x: str(x.get("date") or ""))
    index = {str(x.get("date") or "")[:10]: i for i, x in enumerate(bars)}
    samples = []
    for signal in sorted((dict(x) for x in signals if isinstance(x, dict)),
                         key=lambda x: str(x.get("availableFrom") or "")):
        effective = str(signal.get("effectiveFrom") or "")[:10]
        available = str(signal.get("availableFrom") or "")
        detected = str(signal.get("detectedAt") or available)
        if not effective or not available or available > detected or effective not in index:
            continue
        i = index[effective]
        # The bar used to trigger a signal must have been available by detection.
        if str(bars[i].get("availableFrom") or bars[i].get("date") or "") > detected:
            continue
        row = {"signalId": signal.get("id"), "effectiveFrom": effective}
        for horizon in (1, 5, 20):
            row[f"return{horizon}dPct"] = _returns(bars, i, horizon)
        future = bars[i + 1:min(len(bars), i + 21)]
        start = bars[i].get("close")
        if isinstance(start, (int, float)) and start > 0 and future:
            changes = [(float(x["close"]) / float(start) - 1.0) * 100.0 for x in future
                       if isinstance(x.get("close"), (int, float))]
            row["maxRisePct"] = max(changes) if changes else None
            row["maxDrawdownPct"] = min(changes) if changes else None
        else:
            row["maxRisePct"], row["maxDrawdownPct"] = None, None
        samples.append(row)
    ret5 = [x["return5dPct"] for x in samples if x.get("return5dPct") is not None]
    n = len(ret5)
    hit = sum(1 for x in ret5 if x > 0) / n if n else None
    ci = None
    if n and hit is not None:
        half = 1.96 * sqrt(hit * (1.0 - hit) / n)
        ci = [round(max(0.0, hit - half), 4), round(min(1.0, hit + half), 4)]
    # A sample-size threshold only makes the heuristic testable.  It does not
    # by itself prove economic validity, so a >=30 sample remains experimental
    # until a separately frozen rule-specific directional hypothesis passes.
    classification = "experimental" if n >= min_validated_samples else "insufficient_data"
    return {"methodVersion": METHOD_VERSION, "classification": classification,
            "sampleSize": n, "occurrences": len(samples),
            "hitRate5d": (round(hit, 4) if hit is not None else None),
            "falsePositiveRate5d": (round(1.0 - hit, 4) if hit is not None else None),
            "confidenceInterval95": ci,
            "average1dPct": _average(samples, "return1dPct"),
            "average5dPct": _average(samples, "return5dPct"),
            "average20dPct": _average(samples, "return20dPct"),
            "maxRisePct": _max_value(samples, "maxRisePct"),
            "maxDrawdownPct": _min_value(samples, "maxDrawdownPct"),
            "regimeBreakdown": {}, "samples": samples,
            "noFutureLeakage": True}


def _average(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [float(x[key]) for x in rows if isinstance(x.get(key), (int, float))]
    return round(sum(vals) / len(vals), 4) if vals else None


def _max_value(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [float(x[key]) for x in rows if isinstance(x.get(key), (int, float))]
    return round(max(vals), 4) if vals else None


def _min_value(rows: Sequence[Dict[str, Any]], key: str) -> Optional[float]:
    vals = [float(x[key]) for x in rows if isinstance(x.get(key), (int, float))]
    return round(min(vals), 4) if vals else None


def heuristic_inventory(turning_points: Iterable[Dict[str, Any]],
                        backtests: Optional[Iterable[Dict[str, Any]]] = None
                        ) -> List[Dict[str, Any]]:
    points = [x for x in turning_points if isinstance(x, dict)]
    tests = [x for x in (backtests or []) if isinstance(x, dict)]
    out = []
    for rule_id, name, classification, mapped_rule in HEURISTICS:
        matched = [x for x in points if mapped_rule and x.get("ruleId") == mapped_rule]
        matching_tests = [x for x in tests if x.get("ruleId") == mapped_rule]
        latest_test = matching_tests[-1] if matching_tests else {}
        sample_size = int(latest_test.get("sampleSize") or len(matched))
        evaluated_class = str(latest_test.get("classification") or "")
        allowed_class = (evaluated_class if evaluated_class in {
            "validated", "experimental", "rejected", "insufficient_data"}
                         else "experimental" if sample_size >= 30 and matched
                         else "insufficient_data")
        out.append({"ruleId": rule_id, "ruleName": name,
                    "classification": allowed_class,
                    "sampleSize": sample_size,
                    "historicalTendency": (latest_test.get("classification")
                                           or "not_evaluated"),
                    "currentState": "triggered" if matched else "not_observed",
                    "supportingFacts": list((matched[-1].get("facts") or [])[:3]) if matched else [],
                    "failureConditions": ["単独の売買判断に使用しない", "公表時刻前のデータを使用しない"],
                    "lastTriggered": matched[-1].get("effectiveFrom") if matched else None,
                    "outcomeSummary": (latest_test.get("summary")
                                       or "insufficient_data"),
                    "methodVersion": METHOD_VERSION})
    return out


def daily_changes(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes = []
    for point in reversed(view.get("turningPoints") or []):
        facts = point.get("facts") or []
        if facts:
            changes.append({"id": point.get("id"), "status": "new",
                            "category": point.get("ruleId"), "summaryJa": str(facts[0]),
                            "effectiveFrom": point.get("effectiveFrom")})
        if len(changes) >= 5:
            break
    return changes


def anomaly_desk(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Only evidence-backed discrepancies; never synthesize a cause."""
    rows = {x.get("seriesId"): x for x in view.get("table") or []}
    out = []
    foreign = rows.get("flow.foreign") or {}
    eps = rows.get("valuation.eps") or {}
    per = rows.get("valuation.per") or {}
    breadth6 = rows.get("breadth.prime.ratio6") or rows.get("breadth.ratio6") or {}
    breadth25 = rows.get("breadth.prime.ratio25") or rows.get("breadth.ratio25") or {}
    if isinstance(eps.get("previousChange"), (int, float)) and eps["previousChange"] > 0 \
            and isinstance(per.get("previousChange"), (int, float)) and per["previousChange"] < 0:
        out.append(_anomaly("eps_up_per_down", ["EPS上昇", "PER低下"],
                            "EPS上昇時は評価維持を想定", "PER縮小", "medium"))
    if isinstance(foreign.get("latestValue"), (int, float)) and foreign["latestValue"] > 0:
        # A price relation is not in the ledger payload; do not invent it.
        pass
    if all(isinstance(x.get("previousChange"), (int, float)) for x in (breadth6, breadth25)) \
            and breadth6["previousChange"] < breadth25["previousChange"]:
        out.append(_anomaly("breadth_internal_divergence", ["6日騰落の変化が25日を下回る"],
                            "短期と中期の方向一致", "短期内部悪化", "low"))
    return out[:5]


def _anomaly(anomaly_id: str, facts: List[str], expected: str, observed: str,
             confidence: str) -> Dict[str, Any]:
    return {"id": anomaly_id, "facts": facts, "expectedRelationship": expected,
            "observedRelationship": observed, "discrepancy": f"{expected} / {observed}",
            "confidence": confidence, "possibleExplanations": [], "causeUnconfirmed": True}


def decision_change_conditions(view: Dict[str, Any]) -> List[Dict[str, Any]]:
    summary = view.get("summary") or {}
    conditions = []
    if summary.get("shortFuel") == "UNKNOWN":
        conditions.append({"type": "positioning", "conditionJa": "二市場合計信用残の公表値取得で再判定",
                           "status": "data_required"})
    if summary.get("epsMomentum") == "UNKNOWN":
        conditions.append({"type": "valuation", "conditionJa": "日経EPS/PER履歴取得で評価帯を再判定",
                           "status": "data_required"})
    if summary.get("breadth") == "UNKNOWN":
        conditions.append({"type": "breadth", "conditionJa": "騰落銘柄数の正式値取得で内部環境を再判定",
                           "status": "data_required"})
    return conditions[:3]


def operating_sheet(view: Dict[str, Any], calendar: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    changes = daily_changes(view)
    anomalies = anomaly_desk(view)
    conditions = decision_change_conditions(view)
    section_names = ["Market Calendar / Session", "Important Events", "Market Posture",
                     "Market Ledger Changes", "Credit Positioning", "Investor Flows",
                     "Earnings / Valuation", "Breadth", "Relative Strength", "Rotation",
                     "Price Structure", "Reaction Anomalies", "Relationship Breaks",
                     "Latest Turning Points", "What Changes the View", "Data Quality"]
    available = {"Market Calendar / Session": bool(calendar),
                 "Market Ledger Changes": bool(changes),
                 "Credit Positioning": view.get("summary", {}).get("shortFuel") != "UNKNOWN",
                 "Investor Flows": view.get("summary", {}).get("foreignFlow") != "UNKNOWN",
                 "Earnings / Valuation": view.get("summary", {}).get("epsMomentum") != "UNKNOWN",
                 "Breadth": view.get("summary", {}).get("breadth") != "UNKNOWN",
                 "Latest Turning Points": bool(view.get("turningPoints")),
                 "What Changes the View": bool(conditions), "Data Quality": True}
    return {"schemaVersion": SCHEMA_VERSION, "methodVersion": METHOD_VERSION,
            "asOf": view.get("asOf"), "sections": [
                {"order": i + 1, "name": name,
                 "status": "available" if available.get(name, False) else "refer_existing_surface"}
                for i, name in enumerate(section_names)],
            "dailyChanges": changes[:5], "anomalyDesk": anomalies,
            "decisionChangeConditions": conditions[:3],
            "today": (anomalies + changes)[:3], "calendar": calendar or {},
            "noteJa": "事実と公表時刻のみを使用。原因は確認済みの場合だけ表示し、自動売買は行いません。"}


def build_phase3(view: Dict[str, Any], calendar: Optional[Dict[str, Any]] = None,
                 status_overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    sheet = operating_sheet(view, calendar)
    return {"phase3": sheet,
            "sourceOfTruthMatrix": source_of_truth_matrix(status_overrides),
            "heuristics": heuristic_inventory(view.get("turningPoints") or [],
                                                view.get("backtests") or []),
            "backtestPolicy": {"method": "walk_forward", "noFutureLeakage": True,
                               "minimumValidatedSamples": 30,
                               "status": "insufficient_data" if not view.get("turningPoints") else "eligible"},
            "automaticAiCalls": 0}
