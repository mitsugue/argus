"""Explicit scales and descriptive scenario paths for the Japan index.

The ensemble is a research forecast, not a calibrated probability. A reference
frequency is not an accuracy claim. The price scale requires definition-aligned
index valuation; ETF or capitalization-weighted PER is not a substitute.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Mapping, Sequence

from jp_market_engine import _instant

VALUATION_BASIS = "NIKKEI_225_INDEX_BASED_PER"
METHOD = "jp-index-analog-median-research-v1"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return ordered[left] + (ordered[right] - ordered[left]) * (position - left)


def index_valuation_scale(valuation: Mapping[str, Any] | None, *, cutoff: str,
                          anchor_date: str, anchor_price: float) -> dict[str, Any]:
    result = {"status": "UNAVAILABLE", "reason": "missing_index_valuation",
              "instrumentId": "NIKKEI_225_INDEX", "currency": "JPY",
              "eps": None, "per": None, "anchorPrice": None}
    if not valuation:
        return result
    if valuation.get("instrumentId") != "NIKKEI_225_INDEX" or valuation.get("basis") != VALUATION_BASIS:
        return {**result, "reason": "incompatible_index_valuation_definition"}
    if valuation.get("currency") != "JPY" or valuation.get("date") != anchor_date:
        return {**result, "reason": "incompatible_valuation_currency_or_session"}
    limit = _instant(cutoff)
    known = [_instant(valuation.get(key)) for key in ("availableFrom", "knownAt") if valuation.get(key)]
    if not limit or not known or any(value is None or value > limit for value in known):
        return {**result, "reason": "valuation_not_known_at_cutoff"}
    if not valuation.get("sourceRef"):
        return {**result, "reason": "valuation_source_required"}
    index = _finite(valuation.get("indexClose"))
    per = _finite(valuation.get("per"))
    anchor = _finite(anchor_price)
    if any(value is None or value <= 0 for value in (index, per, anchor)):
        return {**result, "reason": "invalid_valuation_value"}
    if not math.isclose(index, anchor, rel_tol=1e-6, abs_tol=.01):
        return {**result, "reason": "valuation_anchor_price_mismatch"}
    eps = index / per
    if not math.isfinite(eps) or eps <= 0:
        return {**result, "reason": "invalid_derived_index_eps"}
    return {**result, "status": "AVAILABLE", "reason": None,
            "eps": eps, "per": per, "anchorPrice": anchor, "date": anchor_date,
            "basis": VALUATION_BASIS, "sourceRef": valuation["sourceRef"],
            "availableFrom": valuation.get("availableFrom"), "knownAt": valuation.get("knownAt"),
            "epsDerivation": "same-session index close / index-based PER",
            "shapeToYenFormula": "current index EPS * current index PER * shape / 100",
            "assumptions": ["constant_current_index_eps_for_reference_mapping",
                            "shape_returns_are_not_observed_historical_per_changes"],
            "revocationConditions": ["new_index_eps_or_definition", "anchor_session_changes"],
            "perClippingApplied": False}


def convert_shape_to_yen(points: Sequence[Mapping[str, Any]], *, scale: Mapping[str, Any]) -> list[dict[str, Any]]:
    if scale.get("status") != "AVAILABLE" or scale.get("basis") != VALUATION_BASIS:
        return []
    eps, per = _finite(scale.get("eps")), _finite(scale.get("per"))
    if eps is None or per is None or min(eps, per) <= 0:
        return []
    converted = []
    for row in points:
        value = _finite(row.get("value"))
        if value is None or value <= 0:
            raise ValueError("invalid_shape_value")
        price = eps * per * value / 100
        if not math.isfinite(price):
            raise ValueError("price_conversion_overflow")
        converted.append({**dict(row), "shapeValue": value, "value": price,
                          "unit": "JPY_INDEX_POINTS"})
    return converted


def reference_ensemble(selection: Mapping[str, Any], paths: Sequence[Mapping[str, Any]], *,
                       horizon_sessions: int = 5, flat_threshold_pct: float = .5) -> dict[str, Any]:
    """Summarize complete, uniquely selected historical paths after selection.

    This may be drawn as a provisional calculation-engine forecast. Its band
    is the 25th–75th percentile of these past outcomes, NOT a future coverage
    interval. Small samples and failed independent validation remain visible.
    """
    if isinstance(horizon_sessions, bool) or horizon_sessions not in (1, 5, 10, 20):
        raise ValueError("unsupported_scenario_horizon")
    threshold = _finite(flat_threshold_pct)
    if threshold is None or threshold < 0:
        raise ValueError("invalid_flat_classification_threshold")
    selection_cutoff = _instant(selection.get("informationCutoff"))
    if selection_cutoff is None:
        raise ValueError("selection_information_cutoff_required")
    eligible = {row["snapshotId"] for row in selection.get("selected", [])}
    admitted: dict[str, list[float]] = {}
    for path in paths:
        identifier = path.get("snapshotId")
        points = path.get("subsequentReference", [])
        path_cutoff = _instant(path.get("displayCutoff"))
        if path_cutoff is None or path_cutoff > selection_cutoff:
            continue
        if identifier not in eligible or identifier in admitted:
            continue
        if path.get("scale") != "ANCHOR_100" or path.get("status") != "AVAILABLE" \
                or path.get("horizonSessions") != horizon_sessions or len(points) != horizon_sessions + 1:
            continue
        values = [_finite(point.get("value")) for point in points]
        if any(v is None or v <= 0 for v in values) or values[0] != 100 \
                or [point.get("offsetSessions") for point in points] != list(range(horizon_sessions + 1)):
            continue
        admitted[identifier] = values
    counts = {"up": 0, "flat": 0, "down": 0}
    for path in admitted.values():
        change = path[-1] - 100
        counts["up" if change > threshold else "down" if change < -threshold else "flat"] += 1
    sample = len(admitted)
    line = []
    band = []
    if sample >= 2:
        for session in range(horizon_sessions + 1):
            values = [path[session] for path in admitted.values()]
            line.append({"offsetSessions": session, "value": statistics.median(values)})
            band.append({"offsetSessions": session, "lower": _quantile(values, .25),
                         "upper": _quantile(values, .75)})
    return {
        "method": METHOD, "selectionId": selection.get("selectionId"),
        "instrumentId": "NIKKEI_225_INDEX", "horizonSessions": horizon_sessions,
        "classification": {"unit": "PERCENT", "upAbove": threshold,
                           "flatInclusive": [-threshold, threshold], "downBelow": -threshold},
        "status": "PROVISIONAL_RESEARCH_FORECAST" if line else "INSUFFICIENT_COMPLETE_ANALOGS",
        "forecastLine": line, "forecastBand": band, "scale": "ANCHOR_100",
        "frequency": {"meaning": "SELECTED_HISTORICAL_OUTCOME_FREQUENCY", "sampleCount": sample,
                      "counts": counts, "fractions": {key: count / sample if sample else None
                                                      for key, count in counts.items()}},
        "bandMeaning": "selected historical path quartiles; not a predictive coverage interval",
        "predictiveProbabilities": None, "predictionConfidence": None,
        "validationStatus": "UNVALIDATED", "baselineAdditionalBenefitVerified": False,
        "selectionCoverage": selection.get("status"), "actionAuthority": False,
    }


def comparison_document(current: Mapping[str, Any], selection: Mapping[str, Any],
                        paths: Sequence[Mapping[str, Any]], ensemble: Mapping[str, Any], *,
                        scale: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Project one set of calculation identities into the chart contract."""
    if current.get("status") != "AVAILABLE" or not current.get("window"):
        raise ValueError("actual_index_window_required")
    if selection.get("currentSnapshotId") != current.get("snapshotId") or \
            ensemble.get("selectionId") != selection.get("selectionId"):
        raise ValueError("chart_calculation_identity_mismatch")
    anchor_price = current["window"][-1]["close"]
    use_yen = bool(scale and scale.get("status") == "AVAILABLE")
    if use_yen and (scale.get("date") != current.get("anchorDate") or
                    not math.isclose(scale.get("anchorPrice", 0), anchor_price, abs_tol=.01)):
        raise ValueError("chart_valuation_anchor_mismatch")

    def convert(points):
        return convert_shape_to_yen(points, scale=scale) if use_yen else [dict(p) for p in points]

    actual = [{"offsetSessions": index - len(current["window"]) + 1,
               "date": row["date"], "value": row["close"] / anchor_price * 100}
              for index, row in enumerate(current["window"])]
    by_id = {path["snapshotId"]: path for path in paths}
    groups = {"priceShape": "基準値を合わせた価格形状を比較",
              "marketState": "同じ尺度の市場状態を比較",
              "conditionOrder": "条件の発生順序を比較",
              "materialReaction": "同種の材料に対する価格反応を比較"}
    feature_labels = {
        "credit.ratio": "二市場信用倍率", "credit.ratio_change": "二市場信用倍率の変化",
        "credit.loss_pct": "信用評価損失率", "margin1570.ratio": "日経レバ信用倍率",
        "margin1570.long_change_pct": "日経レバ買残の変化率", "margin1570.short_change_pct": "日経レバ売残の変化率",
        "relative_jp_us.return20": "日米相対力", "vix.level": "VIX水準", "vix.change5": "VIXの変化",
        "vix.macd_histogram": "VIXのMACD", "foreign_flow.net4w": "海外投資家の4週フロー",
        "fx.usdjpy_change5": "ドル円の変化率", "rate.jp10y_change5": "日本10年金利の変化幅",
        "rate.us10y_change5": "米国10年金利の変化幅", "nt.ratio_change5": "NT倍率の変化率",
        "event.sq_sessions": "SQまでの営業日数",
    }
    def display_value(value, unit):
        labels = {"RATIO": "倍", "PERCENT": "%", "INDEX_POINTS": "ポイント",
                  "PERCENTAGE_POINTS": "%ポイント", "TRADING_SESSIONS": "営業日", "JPY": "円"}
        if unit == "JPY" and abs(value) >= 100_000_000:
            return f"{value / 100_000_000:,.1f}億円"
        return f"{value:,.3f}".rstrip("0").rstrip(".") + labels.get(unit, "")

    candidates = []
    for selected in selection.get("selected", []):
        path = by_id.get(selected["snapshotId"])
        if not path:
            continue
        differences = []
        for difference in selected.get("importantDifferences", []):
            if "currentValue" in difference:
                label = feature_labels.get(difference["feature"], "市場指標")
                differences.append(f"{label}：現在条件 {display_value(difference['currentValue'], difference['unit'])}、比較時 {display_value(difference['comparisonValue'], difference['unit'])}")
        if selected["componentDistances"].get("conditionOrder", 0):
            differences.append("条件が発生した順序には違いがあります")
        if selected["componentDistances"].get("materialReaction", 0):
            differences.append("同種の材料に対する価格反応には違いがあります")
        if selected["missingFeatures"]:
            differences.append(f"市場指標のうち{len(selected['missingFeatures'])}系列が比較できません")
        if selected["missingGroups"]:
            missing_labels = {"marketState": "市場状態", "conditionOrder": "条件の順序",
                              "materialReaction": "材料反応", "priceShape": "価格形状"}
            differences.append("・".join(missing_labels[key] for key in selected["missingGroups"]) + "の根拠が不足しています")
        differences.append("過去時点の改訂前データは検証できていません")
        candidates.append({"snapshotId": selected["snapshotId"], "anchorDate": path["anchorDate"],
                           "comparisonKind": selected["comparisonKind"],
                           "comparison": convert(path["comparison"]),
                           "subsequentReference": convert(path["subsequentReference"]),
                           "missingFeatures": selected["missingFeatures"], "missingGroups": selected["missingGroups"],
                           "similarReasons": [groups[key] for key in selected["similarityReasons"]],
                           "differences": differences})
    converted_band = []
    for point in ensemble["forecastBand"]:
        bounds = convert([{"offsetSessions": point["offsetSessions"], "value": point[key]}
                          for key in ("lower", "upper")])
        converted_band.append({"offsetSessions": point["offsetSessions"],
                               "lower": bounds[0]["value"], "upper": bounds[1]["value"]})
    return {
        "schemaVersion": "jp-market-comparison-v1", "informationCutoff": current["cutoff"],
        "anchorDate": current["anchorDate"], "actualAnchorPrice": anchor_price,
        "unit": "JPY_INDEX_POINTS" if use_yen else "ANCHOR_100", "actual": convert(actual),
        "candidates": candidates,
        "forecast": {"status": ensemble["status"], "line": convert(ensemble["forecastLine"]),
                     "band": converted_band, "horizonSessions": ensemble["horizonSessions"],
                     "validationStatus": ensemble["validationStatus"],
                     "sampleCount": ensemble["frequency"]["sampleCount"],
                     "counts": ensemble["frequency"]["counts"],
                     "flatThresholdPct": ensemble["classification"]["upAbove"]},
        "scaleExplanation": ("同じ基準日の指数EPS×指数PER×比較値/100で円換算しています。短期間のEPS一定を仮定しています。"
                             if use_yen else "現在と各過去局面の基準日を100に合わせた形状比較です。整合する指数EPS/PERがないため円換算は表示していません。"),
        "limitations": ["過去の参考経路は確定した未来ではありません。",
                        "単純トレンド等に対する独立期間の追加効果は未検証です。",
                        "取得済みの終値までを表示し、欠測した価格は補間していません。"],
    }


def cached_index_comparison(bars: Sequence[Mapping[str, Any]], *, cutoff: str,
                            session_dates: Sequence[str], horizon_sessions: int = 5,
                            acquired_at: str | None = None,
                            valuation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Connect cached daily observations to the existing four-layer calculation.

    Historical bars are the source's currently reported history. Their session
    close availability is NOT proof of an archived, unrevised historical vintage.
    The caller supplies independently verified exchange sessions; missing bars
    cannot silently compress a twenty-session comparison window.
    """
    from jp_market_analogs import (AnalogPolicy, INSTRUMENT, _hash, build_episode,
                                  reference_path, select_episodes)
    from jp_market_engine import point_in_time_rows

    if isinstance(horizon_sessions, bool) or horizon_sessions not in (1, 5, 10, 20):
        raise ValueError("unsupported_reference_horizon")
    if len(bars) > 1000:
        raise ValueError("index_history_bound_exceeded")
    if list(session_dates) != sorted(set(session_dates)):
        raise ValueError("unique_ordered_session_calendar_required")
    policy = AnalogPolicy()
    visible, visibility = point_in_time_rows(
        [dict(row) for row in bars if row.get("instrumentId") == INSTRUMENT], cutoff)
    visible.sort(key=lambda row: row.get("date", ""))
    base = {"status": "unavailable", "automaticAiCalls": 0, "actionAuthority": False,
            "informationCutoff": cutoff, "lastSuccessfulAcquisitionAt": acquired_at,
            "historicalVintageVerified": False, "comparison": None,
            "sourceRef": "yahoo:chart:^N225", "sourceVisibility": visibility}
    current = build_episode(cutoff=cutoff, bars=visible, policy=policy)
    if current["status"] != "AVAILABLE":
        return {**base, "reason": "insufficient_complete_index_history"}
    # Limit candidates to dates whose complete lookback exists on the official
    # calendar. The source's list of observed dates is never itself the calendar.
    positions = {day: i for i, day in enumerate(session_dates)}
    def complete_window(episode):
        position = positions.get(episode["anchorDate"])
        return position is not None and position >= policy.lookback_sessions and \
            [row["date"] for row in episode["window"]] == list(
                session_dates[position - policy.lookback_sessions:position + 1])
    if not complete_window(current):
        return {**base, "reason": "current_exchange_sessions_missing"}
    candidates = []
    for index in range(policy.lookback_sessions, len(visible) - policy.lookback_sessions - 1):
        row = visible[index]
        episode = build_episode(cutoff=row["date"] + "T23:59:59Z",
                                bars=visible[index - policy.lookback_sessions:index + 1], policy=policy)
        if episode["status"] == "AVAILABLE" and complete_window(episode):
            candidates.append(episode)
    selection = select_episodes(current, candidates, session_dates=session_dates, policy=policy)
    selected = {row["snapshotId"] for row in selection["selected"]}
    paths = [reference_path(episode, later_bars=visible, display_cutoff=cutoff,
                            session_dates=session_dates, horizon_sessions=horizon_sessions, policy=policy)
             for episode in candidates if episode["snapshotId"] in selected]
    ensemble = reference_ensemble(selection, paths, horizon_sessions=horizon_sessions)
    scale = index_valuation_scale(valuation, cutoff=cutoff, anchor_date=current["anchorDate"],
                                  anchor_price=current["window"][-1]["close"])
    document = comparison_document(current, selection, paths, ensemble, scale=scale)
    document["limitations"].append("過去比較には取得元が現在報告する履歴を使用しています。改訂前の履歴の再現は未検証です。")
    document["limitations"].append("市場状態・条件の順序・材料反応の履歴接続は未完了のため、現段階では価格形状の部分比較です。")
    document["calculationIdentity"] = {"currentSnapshotId": current["snapshotId"],
                                       "selectionId": selection["selectionId"],
                                       "sourceContentHash": _hash(visible)}
    document["valuationStatus"] = scale["status"]
    return {**base, "status": "available", "reason": None, "comparison": document,
            "selection": selection, "valuation": scale,
            "historyCoverage": {"sourceBars": len(visible), "candidateCount": len(candidates),
                                "calendarStart": session_dates[0] if session_dates else None,
                                "calendarEnd": session_dates[-1] if session_dates else None}}
