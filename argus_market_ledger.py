# -*- coding: utf-8 -*-
"""Append-only SHO-inspired market ledger Phase 1 (pure, stdlib-only)."""
import csv
import hashlib
import io
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = "argus-market-ledger-v1"
METHOD_VERSION = "market-ledger-phase1-v1"
CREDIT_THRESHOLD_YEN = 800_000_000_000
BREADTH_SHARP_DROP_POINTS = 20.0
SOURCE_KINDS = {"official", "licensed", "manual", "derived"}
OBSERVATION_STATUSES = {"live", "delayed", "missing", "revised"}

SERIES = {
    "credit.short_balance": ("JPY", "二市場合計売り残", "manual_csv", "official"),
    "credit.long_balance": ("JPY", "二市場合計買い残", "manual_csv", "official"),
    "credit.ratio": ("ratio", "信用倍率", "derived", "derived"),
    "credit.valuation_loss_pct": ("percent", "信用評価損益率", "manual_csv", "licensed"),
    "flow.foreign": ("JPY", "海外投資家", "jquants_or_manual", "official"),
    "flow.individual": ("JPY", "個人", "jquants_or_manual", "official"),
    "flow.investment_trust": ("JPY", "投資信託", "jquants_or_manual", "official"),
    "flow.trust_bank": ("JPY", "信託銀行", "jquants_or_manual", "official"),
    "flow.proprietary": ("JPY", "証券自己", "jquants_or_manual", "official"),
    "valuation.nikkei": ("JPY", "日経平均", "nikkei_or_manual", "official"),
    "valuation.per": ("ratio", "日経平均PER", "nikkei_or_manual", "official"),
    "valuation.pbr": ("ratio", "日経平均PBR", "nikkei_or_manual", "official"),
    "breadth.advancers": ("count", "値上がり銘柄数", "official_or_manual", "official"),
    "breadth.decliners": ("count", "値下がり銘柄数", "official_or_manual", "official"),
    "breadth.ratio6": ("percent", "6日騰落レシオ", "derived", "derived"),
    "breadth.ratio10": ("percent", "10日騰落レシオ", "derived", "derived"),
    "breadth.ratio15": ("percent", "15日騰落レシオ", "derived", "derived"),
    "breadth.ratio25": ("percent", "25日騰落レシオ", "derived", "derived"),
    "breadth.topixProxyClose": ("JPY", "TOPIX連動ETF調整終値", "jquants", "derived"),
    "breadth.prime.advancers": ("count", "Prime値上がり銘柄数", "jquants", "derived"),
    "breadth.prime.decliners": ("count", "Prime値下がり銘柄数", "jquants", "derived"),
    "breadth.prime.unchanged": ("count", "Prime変わらず銘柄数", "jquants", "derived"),
    "breadth.prime.unavailable": ("count", "Prime比較不能銘柄数", "jquants", "derived"),
    "breadth.prime.noTrade": ("count", "Prime無取引銘柄数", "jquants", "derived"),
    "breadth.prime.missingPrice": ("count", "Prime価格欠損銘柄数", "jquants", "derived"),
    "breadth.prime.eligibleCount": ("count", "Prime比較対象銘柄数", "jquants", "derived"),
    "breadth.prime.totalUniverseCount": ("count", "Prime母集団銘柄数", "jquants", "derived"),
    "breadth.first_section.advancers": ("count", "旧東証一部値上がり銘柄数", "jquants", "derived"),
    "breadth.first_section.decliners": ("count", "旧東証一部値下がり銘柄数", "jquants", "derived"),
    "breadth.first_section.unchanged": ("count", "旧東証一部変わらず銘柄数", "jquants", "derived"),
    "breadth.first_section.unavailable": ("count", "旧東証一部比較不能銘柄数", "jquants", "derived"),
    "breadth.first_section.noTrade": ("count", "旧東証一部無取引銘柄数", "jquants", "derived"),
    "breadth.first_section.missingPrice": ("count", "旧東証一部価格欠損銘柄数", "jquants", "derived"),
    "breadth.first_section.eligibleCount": ("count", "旧東証一部比較対象銘柄数", "jquants", "derived"),
    "breadth.first_section.totalUniverseCount": ("count", "旧東証一部母集団銘柄数", "jquants", "derived"),
    "breadth.all.advancers": ("count", "全市場値上がり銘柄数", "jquants", "derived"),
    "breadth.all.decliners": ("count", "全市場値下がり銘柄数", "jquants", "derived"),
    "breadth.all.unchanged": ("count", "全市場変わらず銘柄数", "jquants", "derived"),
    "breadth.all.unavailable": ("count", "全市場比較不能銘柄数", "jquants", "derived"),
    "breadth.all.noTrade": ("count", "全市場無取引銘柄数", "jquants", "derived"),
    "breadth.all.missingPrice": ("count", "全市場価格欠損銘柄数", "jquants", "derived"),
    "breadth.all.eligibleCount": ("count", "全市場比較対象銘柄数", "jquants", "derived"),
    "breadth.all.totalUniverseCount": ("count", "全市場母集団銘柄数", "jquants", "derived"),
    "breadth.prime.ratio6": ("percent", "Prime 6日騰落レシオ", "derived", "derived"),
    "breadth.prime.ratio10": ("percent", "Prime 10日騰落レシオ", "derived", "derived"),
    "breadth.prime.ratio15": ("percent", "Prime 15日騰落レシオ", "derived", "derived"),
    "breadth.prime.ratio25": ("percent", "Prime 25日騰落レシオ", "derived", "derived"),
    "breadth.first_section.ratio6": ("percent", "旧東証一部6日騰落レシオ", "derived", "derived"),
    "breadth.first_section.ratio10": ("percent", "旧東証一部10日騰落レシオ", "derived", "derived"),
    "breadth.first_section.ratio15": ("percent", "旧東証一部15日騰落レシオ", "derived", "derived"),
    "breadth.first_section.ratio25": ("percent", "旧東証一部25日騰落レシオ", "derived", "derived"),
    "breadth.all.ratio6": ("percent", "全市場6日騰落レシオ", "derived", "derived"),
    "breadth.all.ratio10": ("percent", "全市場10日騰落レシオ", "derived", "derived"),
    "breadth.all.ratio15": ("percent", "全市場15日騰落レシオ", "derived", "derived"),
    "breadth.all.ratio25": ("percent", "全市場25日騰落レシオ", "derived", "derived"),
}

BREADTH_PREFIXES = ("breadth", "breadth.first_section", "breadth.prime", "breadth.all")


def empty_state() -> Dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "observations": [], "derivedMetrics": [],
            "turningPoints": [], "backtests": [], "imports": [], "rolledBackImports": [],
            "lastUpdatedAt": None, "methodVersion": METHOD_VERSION,
            "derivedStateDirty": False, "lastRebuiltObservationCount": 0,
            "lastRebuiltAt": None}


def normalize_state(state: Any) -> Dict[str, Any]:
    src = state if isinstance(state, dict) else {}
    out = empty_state()
    for k in ("observations", "derivedMetrics", "turningPoints", "backtests", "imports",
              "rolledBackImports"):
        out[k] = [x for x in (src.get(k) or []) if isinstance(x, dict)] if k != "rolledBackImports" else list(src.get(k) or [])
    out["lastUpdatedAt"] = src.get("lastUpdatedAt")
    # v1 remains backward-compatible: snapshots written before the dirty marker
    # were rebuilt synchronously before persistence, so they are clean on load.
    out["derivedStateDirty"] = bool(src.get("derivedStateDirty", False))
    out["lastRebuiltObservationCount"] = int(
        src.get("lastRebuiltObservationCount", len(out["observations"])) or 0)
    out["lastRebuiltAt"] = src.get("lastRebuiltAt")
    return out


def _hash(obj: Any, n: int = 20) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()[:n]


def state_hash(state: Dict[str, Any]) -> str:
    st = normalize_state(state)
    return _hash({k: st[k] for k in ("observations", "derivedMetrics",
                                     "turningPoints", "backtests", "imports",
                                     "rolledBackImports")}, 32)


def rebuild_required(state: Dict[str, Any]) -> bool:
    """True only when append-only inputs changed since the last derived rebuild."""
    st = normalize_state(state)
    return bool(st["derivedStateDirty"] or
                st["lastRebuiltObservationCount"] != len(st["observations"]))


def _iso_ok(value: Any) -> bool:
    s = str(value or "")
    return len(s) >= 10 and s[4:5] == "-" and s[7:8] == "-"


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("boolean_value")
    try:
        return float(str(value).replace(",", ""))
    except Exception as exc:
        raise ValueError("invalid_number") from exc


def append_observation(state: Dict[str, Any], candidate: Dict[str, Any],
                       *, now_iso: str, import_id: str = "") -> Tuple[Dict[str, Any], Dict[str, Any]]:
    st = normalize_state(state)
    return _append_observation_in_place(st, candidate, now_iso=now_iso,
                                        import_id=import_id)


def _append_observation_in_place(st: Dict[str, Any], candidate: Dict[str, Any],
                                 *, now_iso: str,
                                 import_id: str = "",
                                 prior_index: Optional[Dict[Tuple[str, str], List[Dict[str, Any]]]] = None
                                 ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Validated append for an already-normalized private working copy."""
    sid = str(candidate.get("seriesId") or "")
    if sid not in SERIES:
        raise ValueError("unknown_series")
    period = str(candidate.get("periodEnd") or "")
    available = str(candidate.get("availableFrom") or "")
    if not _iso_ok(period) or not _iso_ok(available):
        raise ValueError("invalid_date")
    expected_unit = SERIES[sid][0]
    unit = str(candidate.get("unit") or expected_unit)
    if unit != expected_unit:
        raise ValueError("unit_mismatch")
    value = _number(candidate.get("value"))
    status = str(candidate.get("status") or ("missing" if value is None else "live"))
    source_kind = str(candidate.get("sourceKind") or SERIES[sid][3])
    if status not in OBSERVATION_STATUSES:
        raise ValueError("invalid_status")
    if source_kind not in SOURCE_KINDS:
        raise ValueError("invalid_source_kind")
    if not str(candidate.get("source") or "").strip():
        raise ValueError("source_required")
    if candidate.get("publishedAt") and not _iso_ok(candidate.get("publishedAt")):
        raise ValueError("invalid_published_at")
    if value is None and status not in ("missing", "delayed"):
        raise ValueError("missing_value_status")
    rolled = set(st["rolledBackImports"])
    if prior_index is None:
        prior = [x for x in st["observations"] if x.get("seriesId") == sid
                 and x.get("periodEnd") == period
                 and x.get("importId") not in rolled]
    else:
        prior = [x for x in prior_index.get((sid, period), [])
                 if x.get("importId") not in rolled]
    if prior and any(x.get("value") == value and x.get("availableFrom") == available
                     and x.get("unit") == unit for x in prior):
        raise ValueError("duplicate_observation")
    revision = max([int(x.get("revision") or 0) for x in prior] or [-1]) + 1
    if prior:
        status = "revised"
    body = {"seriesId": sid, "periodEnd": period,
            "publishedAt": candidate.get("publishedAt") or None,
            "availableFrom": available, "observedAt": str(candidate.get("observedAt") or now_iso),
            "value": value, "unit": unit, "source": str(candidate.get("source") or "manual"),
            "sourceKind": source_kind,
            "revision": revision, "status": status,
            "metadata": dict(candidate.get("metadata") or {}), "importId": import_id or None}
    body["id"] = "mo-" + _hash(body)
    st["observations"].append(body)
    if prior_index is not None:
        prior_index.setdefault((sid, period), []).append(body)
    st["lastUpdatedAt"] = now_iso
    st["derivedStateDirty"] = True
    return st, body


def effective_observations(state: Dict[str, Any], as_of: str) -> List[Dict[str, Any]]:
    st = normalize_state(state)
    rolled = set(st["rolledBackImports"])
    eligible = [x for x in st["observations"] if str(x.get("availableFrom") or "") <= as_of
                and x.get("importId") not in rolled]
    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for row in sorted(eligible, key=lambda x: (str(x.get("seriesId")), str(x.get("periodEnd")),
                                                int(x.get("revision") or 0), str(x.get("observedAt")))):
        latest[(str(row.get("seriesId")), str(row.get("periodEnd")))] = row
    return list(latest.values())


def latest_by_series(state: Dict[str, Any], as_of: str) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for row in effective_observations(state, as_of):
        out.setdefault(str(row.get("seriesId")), []).append(row)
    for rows in out.values():
        rows.sort(key=lambda x: str(x.get("periodEnd")))
    return out


def advance_decline_ratio(advancers: Iterable[float], decliners: Iterable[float]) -> Optional[float]:
    up, down = sum(float(x) for x in advancers), sum(float(x) for x in decliners)
    return None if down <= 0 else round(up / down * 100.0, 2)


def _metric(metric_id: str, as_of: str, value: Optional[float], unit: str,
            inputs: List[Dict[str, Any]], classification: str = "derived") -> Dict[str, Any]:
    effective_as_of = max([str(x.get("periodEnd") or "") for x in inputs] or [as_of[:10]])
    body = {"metricId": metric_id, "asOf": effective_as_of, "value": value, "unit": unit,
            "inputObservationIds": [x["id"] for x in inputs], "methodVersion": METHOD_VERSION,
            "classification": classification, "status": "live" if value is not None else "missing"}
    body["id"] = "mm-" + _hash(body)
    return body


def derived_history(state: Dict[str, Any], as_of: str) -> Dict[str, List[Dict[str, Any]]]:
    by = latest_by_series(state, as_of)
    out: Dict[str, List[Dict[str, Any]]] = {}
    def add(row: Dict[str, Any]) -> None:
        out.setdefault(row["metricId"], []).append(row)
    def pairs(left: str, right: str) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        rhs = {x["periodEnd"]: x for x in (by.get(right) or [])}
        return [(x, rhs[x["periodEnd"]]) for x in (by.get(left) or [])
                if x["periodEnd"] in rhs]
    for short, long in pairs("credit.short_balance", "credit.long_balance"):
        value = (None if not short.get("value") or short["value"] <= 0
                 or long.get("value") is None else round(long["value"] / short["value"], 2))
        add(_metric("credit.ratio", as_of, value, "ratio", [short, long]))
    per_pairs = pairs("valuation.nikkei", "valuation.per")
    pbr_pairs = pairs("valuation.nikkei", "valuation.pbr")
    for nk, per in per_pairs:
        eps = None if not per.get("value") or per["value"] <= 0 or nk.get("value") is None else round(nk["value"] / per["value"], 2)
        add(_metric("valuation.eps", as_of, eps, "JPY", [nk, per]))
        for multiple in range(16, 22):
            add(_metric(f"valuation.per{multiple}_level", as_of,
                        None if eps is None else round(eps * multiple), "JPY",
                        [nk, per], "sho_heuristic" if multiple == 21 else "derived"))
    for nk, pbr in pbr_pairs:
        bps = None if not pbr.get("value") or pbr["value"] <= 0 or nk.get("value") is None else round(nk["value"] / pbr["value"], 2)
        add(_metric("valuation.bps", as_of, bps, "JPY", [nk, pbr]))
    for prefix in BREADTH_PREFIXES:
        adv = by.get(f"{prefix}.advancers") or []
        dec = by.get(f"{prefix}.decliners") or []
        dec_by_date = {x["periodEnd"]: x for x in dec}
        joined = [(x, dec_by_date[x["periodEnd"]]) for x in adv
                  if x["periodEnd"] in dec_by_date]
        for days in (6, 10, 15, 25):
            for end in range(days, len(joined) + 1):
                sub = joined[end - days:end]
                values_ok = all(a.get("value") is not None and d.get("value") is not None
                                for a, d in sub)
                val = (advance_decline_ratio([x[0]["value"] for x in sub],
                                             [x[1]["value"] for x in sub])
                       if values_ok else None)
                add(_metric(f"{prefix}.ratio{days}", as_of, val, "percent",
                            [z for pair in sub for z in pair], "sho_heuristic"))
    for rows in out.values():
        rows.sort(key=lambda x: str(x.get("asOf")))
    return out


def derive_metrics(state: Dict[str, Any], as_of: str) -> List[Dict[str, Any]]:
    history = derived_history(state, as_of)
    return [rows[-1] for rows in history.values() if rows]


def _turn(rule: str, effective: str, available: str, inputs: List[Dict[str, Any]],
          direction: str, severity: str, facts: List[str], classification: str,
          detected_at: str, live: bool) -> Dict[str, Any]:
    body = {"ruleId": rule, "ruleVersion": "v1", "detectedAt": detected_at,
            "effectiveFrom": effective, "availableFrom": available,
            "inputObservationIds": [x["id"] for x in inputs],
            "classification": classification, "detectionMode": "live" if live else "retrospective",
            "facts": facts, "direction": direction, "severity": severity}
    body["id"] = "tp-" + _hash({k: v for k, v in body.items() if k != "detectedAt"})
    return body


def detect_turning_points(state: Dict[str, Any], as_of: str, detected_at: str) -> List[Dict[str, Any]]:
    by = latest_by_series(state, as_of)
    points: List[Dict[str, Any]] = []
    shorts = by.get("credit.short_balance") or []
    for prev, cur in zip(shorts, shorts[1:]):
        a, b = prev.get("value"), cur.get("value")
        if a is None or b is None:
            continue
        direction = "up" if a < CREDIT_THRESHOLD_YEN <= b else "down" if a >= CREDIT_THRESHOLD_YEN > b else ""
        if direction:
            points.append(_turn("CREDIT_THRESHOLD_CROSS", cur["periodEnd"], cur["availableFrom"],
                                [prev, cur], direction, "watch",
                                [f"二市場合計売り残が8,000億円を{'上抜け' if direction == 'up' else '下抜け'}",
                                 "閾値側で連続1週"],
                                "sho_heuristic", detected_at, cur["availableFrom"] >= detected_at[:10]))
    longs = by.get("credit.long_balance") or []
    if len(shorts) >= 5 and len(longs) >= 5:
        s4, l4 = shorts[-5:], longs[-5:]
        ratios = [l.get("value") / s.get("value") for l, s in zip(l4, s4)
                  if l.get("value") is not None and s.get("value")]
        if all(s4[i]["value"] > s4[i + 1]["value"] for i in range(4)) and \
                all(l4[i]["value"] < l4[i + 1]["value"] for i in range(4)) and \
                len(ratios) == 5 and ratios[-1] > ratios[0]:
            cur = s4[-1]
            points.append(_turn("POSITIONING_SHIFT", cur["periodEnd"], cur["availableFrom"],
                                s4 + l4, "risk_up", "warning",
                                ["売り残4週減少", "買い残4週増加", "信用倍率悪化"],
                                "derived", detected_at, cur["availableFrom"] >= detected_at[:10]))
    metric_history = derived_history(state, as_of)
    observation_index = {x["id"]: x for x in effective_observations(state, as_of)}
    for prefix in BREADTH_PREFIXES:
        universe = prefix.split(".")[-1] if "." in prefix else "legacy"
        b6_rows = {x["asOf"]: x for x in metric_history.get(f"{prefix}.ratio6", [])
                   if x.get("value") is not None}
        b25_rows = {x["asOf"]: x for x in metric_history.get(f"{prefix}.ratio25", [])
                    if x.get("value") is not None}
        common = sorted(set(b6_rows) & set(b25_rows))
        for prev_date, cur_date in zip(common, common[1:]):
            prev6, prev25 = b6_rows[prev_date], b25_rows[prev_date]
            cur6, cur25 = b6_rows[cur_date], b25_rows[cur_date]
            direction = ("short_above_medium" if prev6["value"] < prev25["value"]
                         and cur6["value"] >= cur25["value"] else
                         "short_below_medium" if prev6["value"] >= prev25["value"]
                         and cur6["value"] < cur25["value"] else "")
            if direction:
                inputs = [x for x in effective_observations(state, as_of)
                          if x.get("id") in set(cur6["inputObservationIds"]
                                                + cur25["inputObservationIds"])]
                available = max([str(x.get("availableFrom") or "") for x in inputs]
                                or [cur_date])
                direction_value = (direction if universe == "legacy"
                                   else f"{universe}:{direction}")
                points.append(_turn(
                    "BREADTH_TURN", cur_date, available, inputs,
                    direction_value, "info",
                    [f"{universe} 6日騰落が25日騰落を"
                     f"{'上抜け' if direction == 'short_above_medium' else '下抜け'}"],
                    "sho_heuristic", detected_at, available >= detected_at[:10]))
        breadth_by_date: Dict[str, Dict[int, Dict[str, Any]]] = {}
        for days in (6, 10, 15, 25):
            for row in metric_history.get(f"{prefix}.ratio{days}", []):
                if row.get("value") is not None:
                    breadth_by_date.setdefault(row["asOf"], {})[days] = row
        for date, rows in sorted(breadth_by_date.items()):
            if len(rows) == 4 and all(rows[d]["value"] > 120 for d in (6, 10, 15, 25)):
                ids = {oid for row in rows.values()
                       for oid in row.get("inputObservationIds", [])}
                inputs = [observation_index[oid] for oid in sorted(ids)
                          if oid in observation_index]
                available = max([str(x.get("availableFrom") or "") for x in inputs]
                                or [date])
                direction_value = ("all_overheated" if universe == "legacy"
                                   else f"{universe}:all_overheated")
                points.append(_turn("BREADTH_TURN", date, available, inputs,
                                    direction_value, "watch",
                                    [f"{universe} 6/10/15/25日騰落がすべて120超"],
                                    "sho_heuristic", detected_at,
                                    available >= detected_at[:10]))
        b6_list = metric_history.get(f"{prefix}.ratio6", [])
        for prev, cur in zip(b6_list, b6_list[1:]):
            if prev.get("value") is None or cur.get("value") is None:
                continue
            threshold_direction = (
                "ratio6_over_120" if prev["value"] <= 120 < cur["value"] else
                "ratio6_under_80" if prev["value"] >= 80 > cur["value"] else "")
            if threshold_direction:
                inputs = [observation_index[oid]
                          for oid in cur.get("inputObservationIds", [])
                          if oid in observation_index]
                available = max([str(x.get("availableFrom") or "") for x in inputs]
                                or [cur["asOf"]])
                direction_value = (threshold_direction if universe == "legacy"
                                   else f"{universe}:{threshold_direction}")
                points.append(_turn(
                    "BREADTH_TURN", cur["asOf"], available, inputs,
                    direction_value, "watch",
                    [f"{universe} 6日騰落レシオが"
                     f"{'120を上抜け' if 'over_120' in threshold_direction else '80を下抜け'}"],
                    "sho_heuristic", detected_at, available >= detected_at[:10]))
        for prev, cur in zip(b6_list, b6_list[1:]):
            if prev.get("value") is not None and cur.get("value") is not None and \
                    prev["value"] - cur["value"] >= BREADTH_SHARP_DROP_POINTS:
                inputs = [observation_index[oid]
                          for oid in cur.get("inputObservationIds", [])
                          if oid in observation_index]
                available = max([str(x.get("availableFrom") or "") for x in inputs]
                                or [cur["asOf"]])
                direction_value = ("short_sharp_drop" if universe == "legacy"
                                   else f"{universe}:short_sharp_drop")
                points.append(_turn("BREADTH_TURN", cur["asOf"], available, inputs,
                                    direction_value, "watch",
                                    [f"{universe} 6日騰落が前回から"
                                     f"{prev['value'] - cur['value']:.2f}pt低下"],
                                    "sho_heuristic", detected_at,
                                    available >= detected_at[:10]))
        proxy_by_date = {x.get("periodEnd"): x for x in
                         (by.get("breadth.topixProxyClose") or [])}
        adv_by_date = {x.get("periodEnd"): x for x in
                       (by.get(f"{prefix}.advancers") or [])}
        dec_by_date = {x.get("periodEnd"): x for x in
                       (by.get(f"{prefix}.decliners") or [])}
        common_divergence = sorted(set(proxy_by_date) & set(adv_by_date)
                                   & set(dec_by_date))
        for prev_date, cur_date in zip(common_divergence, common_divergence[1:]):
            previous_proxy, current_proxy = (proxy_by_date[prev_date],
                                             proxy_by_date[cur_date])
            if not previous_proxy.get("value") or not current_proxy.get("value"):
                continue
            price_change = current_proxy["value"] - previous_proxy["value"]
            previous_balance = ((adv_by_date[prev_date].get("value") or 0)
                                - (dec_by_date[prev_date].get("value") or 0))
            current_balance = ((adv_by_date[cur_date].get("value") or 0)
                               - (dec_by_date[cur_date].get("value") or 0))
            breadth_change = current_balance - previous_balance
            divergence = ("index_up_breadth_down" if price_change > 0
                          and breadth_change < 0 else
                          "index_down_breadth_improves" if price_change < 0
                          and breadth_change > 0 else "")
            if divergence:
                inputs = [previous_proxy, current_proxy, adv_by_date[cur_date],
                          dec_by_date[cur_date]]
                available = max(str(x.get("availableFrom") or "") for x in inputs)
                direction_value = (divergence if universe == "legacy"
                                   else f"{universe}:{divergence}")
                points.append(_turn(
                    "BREADTH_TURN", cur_date, available, inputs,
                    direction_value, "watch",
                    [f"{universe} " + ("指数proxy上昇・breadth悪化" if price_change > 0
                                      else "指数proxy下落・breadth改善")],
                    "sho_heuristic", detected_at, available >= detected_at[:10]))
    # Rollover needs an EPS series, not a single current calculation. Preserve honesty
    # until enough daily valuation observations exist.
    vals = by.get("valuation.nikkei") or []
    pers = by.get("valuation.per") or []
    per_by_date = {x["periodEnd"]: x for x in pers}
    eps_rows = [(x, per_by_date[x["periodEnd"]], x["value"] / per_by_date[x["periodEnd"]]["value"])
                for x in vals if x["periodEnd"] in per_by_date and x.get("value") is not None
                and per_by_date[x["periodEnd"]].get("value")]
    if len(eps_rows) >= 21:
        levels = [e[2] * 21 for e in eps_rows]
        mom5 = eps_rows[-1][2] - eps_rows[-6][2]
        mom20 = eps_rows[-1][2] - eps_rows[-21][2]
        prev_mom5 = eps_rows[-2][2] - eps_rows[-7][2]
        if levels[-1] < max(levels[:-1]) and prev_mom5 > 0 and (mom5 < 0 or mom20 < 0):
            cur = eps_rows[-1][0]
            points.append(_turn("VALUATION_CEILING_ROLLOVER", cur["periodEnd"], cur["availableFrom"],
                                [z for row in eps_rows[-21:] for z in row[:2]], "down", "watch",
                                ["PER21倍水準が直近ピークから低下", "EPSモメンタムが正から負"],
                                "experimental", detected_at, cur["availableFrom"] >= detected_at[:10]))
    unique = {x["id"]: x for x in points}
    return sorted(unique.values(), key=lambda x: (x["effectiveFrom"], x["ruleId"]))


def rebuild(state: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    st = normalize_state(state)
    metrics = derive_metrics(st, now_iso)
    seen_m = {x.get("id") for x in st["derivedMetrics"]}
    st["derivedMetrics"].extend(x for x in metrics
                                if x.get("value") is not None and x["id"] not in seen_m)
    points = detect_turning_points(st, now_iso, now_iso)
    seen_t = {x.get("id") for x in st["turningPoints"]}
    st["turningPoints"].extend(x for x in points if x["id"] not in seen_t)
    if metrics or points or st["observations"]:
        st["lastUpdatedAt"] = now_iso
    st["derivedStateDirty"] = False
    st["lastRebuiltObservationCount"] = len(st["observations"])
    st["lastRebuiltAt"] = now_iso
    return st


def parse_csv(text: str) -> List[Dict[str, Any]]:
    required = {"seriesId", "periodEnd", "availableFrom", "value", "unit", "source"}
    reader = csv.DictReader(io.StringIO(text or ""))
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise ValueError("csv_columns")
    rows = [dict(x) for x in reader]
    if len(rows) > 5000:
        raise ValueError("csv_row_limit")
    return rows


def import_rows(state: Dict[str, Any], rows: List[Dict[str, Any]], *, now_iso: str,
                dry_run: bool = True,
                rebuild_after_commit: bool = True) -> Dict[str, Any]:
    work = normalize_state(state)
    import_id = "mi-" + _hash({"at": now_iso, "rows": rows})
    preview, errors = [], []
    prior_index: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for item in work["observations"]:
        prior_index.setdefault((str(item.get("seriesId")),
                                str(item.get("periodEnd"))), []).append(item)
    for idx, row in enumerate(rows):
        try:
            work, obs = _append_observation_in_place(
                work, row, now_iso=now_iso, import_id=import_id,
                prior_index=prior_index)
            preview.append(obs)
        except ValueError as exc:
            errors.append({"row": idx + 2, "error": str(exc)})
    if errors:
        return {"ok": False, "dryRun": dry_run, "importId": import_id,
                "preview": preview, "errors": errors, "state": normalize_state(state)}
    if dry_run:
        return {"ok": True, "dryRun": True, "importId": import_id,
                "preview": preview, "errors": [], "state": normalize_state(state)}
    work["imports"].append({"importId": import_id, "at": now_iso,
                            "rowCount": len(preview), "status": "committed"})
    # Resumable backfills checkpoint many small append-only batches.  Rebuilding
    # the full derived history after every checkpoint makes runtime grow
    # super-linearly.  A backfill may defer this pure rebuild while observations
    # and the import receipt remain durable, then rebuild once before completion.
    if rebuild_after_commit:
        work = rebuild(work, now_iso)
    return {"ok": True, "dryRun": False, "importId": import_id,
            "preview": preview, "errors": [], "state": work}


def rollback_import(state: Dict[str, Any], import_id: str, now_iso: str) -> Dict[str, Any]:
    st = normalize_state(state)
    known = any(x.get("importId") == import_id for x in st["imports"])
    if not known:
        raise ValueError("unknown_import")
    if import_id not in st["rolledBackImports"]:
        st["rolledBackImports"].append(import_id)
        st["imports"].append({"importId": "rollback-" + import_id, "at": now_iso,
                              "targetImportId": import_id, "status": "rolled_back"})
    return rebuild(st, now_iso)


def public_view(state: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    st = rebuild(state, now_iso) if rebuild_required(state) else normalize_state(state)
    by = latest_by_series(st, now_iso)
    metric_history = derived_history(st, now_iso)
    latest_metrics = {mid: rows[-1] for mid, rows in metric_history.items() if rows}
    table = []
    for sid, (_, label, acquisition, source_kind) in SERIES.items():
        rows = by.get(sid) or []
        drows = metric_history.get(sid) or []
        cur, prev = ((rows[-1] if rows else None),
                     (rows[-2] if len(rows) > 1 else None))
        if not cur and drows:
            cur, prev = drows[-1], (drows[-2] if len(drows) > 1 else None)
        licensed_redacted = source_kind == "licensed"
        values = [x.get("value") for x in (rows or drows)
                  if x.get("value") is not None]
        rank = None
        if values and cur and cur.get("value") is not None:
            rank = round(100 * sum(1 for x in values if x <= cur["value"]) / len(values), 1)
        four_ago = (rows or drows)[-5] if len(rows or drows) >= 5 else None
        direction4 = (None if not cur or not four_ago or cur.get("value") is None
                      or four_ago.get("value") is None else
                      "up" if cur["value"] > four_ago["value"] else
                      "down" if cur["value"] < four_ago["value"] else "flat")
        recent_four = (rows or drows)[-4:]
        four_period_total = (sum(x["value"] for x in recent_four)
                             if sid.startswith("flow.") and len(recent_four) == 4
                             and all(x.get("value") is not None for x in recent_four)
                             else None)
        consecutive_direction_count = None
        if sid.startswith("flow.") and cur and cur.get("value") is not None:
            sign = 1 if cur["value"] > 0 else -1 if cur["value"] < 0 else 0
            consecutive_direction_count = 0
            for item in reversed(rows or drows):
                value = item.get("value")
                item_sign = 1 if value is not None and value > 0 else -1 if value is not None and value < 0 else 0
                if item_sign != sign:
                    break
                consecutive_direction_count += 1
        threshold_distance = (cur["value"] - CREDIT_THRESHOLD_YEN
                              if sid == "credit.short_balance" and cur
                              and cur.get("value") is not None else None)
        threshold_side = ("above" if threshold_distance is not None and threshold_distance >= 0
                          else "below" if threshold_distance is not None else None)
        threshold_streak = None
        if threshold_side and rows:
            threshold_streak = 0
            for item in reversed(rows):
                value = item.get("value")
                side = ("above" if value is not None and value >= CREDIT_THRESHOLD_YEN
                        else "below" if value is not None else None)
                if side != threshold_side:
                    break
                threshold_streak += 1
        table.append({"seriesId": sid, "labelJa": label,
                      "latestValue": (None if licensed_redacted else
                                      cur.get("value") if cur else None),
                      "unit": SERIES[sid][0],
                      "previousChange": (None if licensed_redacted or not cur or not prev or cur.get("value") is None or prev.get("value") is None
                                         else cur["value"] - prev["value"]),
                      "fourPeriodDirection": direction4,
                      "fourPeriodTotal": (None if licensed_redacted else four_period_total),
                      "consecutiveDirectionCount": (None if licensed_redacted else consecutive_direction_count),
                      "thresholdDistance": (None if licensed_redacted else threshold_distance),
                      "thresholdSide": (None if licensed_redacted else threshold_side),
                      "thresholdStreak": (None if licensed_redacted else threshold_streak),
                      "historicalPercentile": rank,
                      "periodEnd": (cur.get("periodEnd") or cur.get("asOf")) if cur else None,
                      "availableFrom": cur.get("availableFrom") if cur else None,
                      "status": ("licensed_redacted" if licensed_redacted and cur else
                                 cur.get("status") if cur else "missing"),
                      "acquisition": acquisition, "sourceKind": source_kind,
                      "history": ([] if licensed_redacted else
                                  [{"periodEnd": x.get("periodEnd") or x.get("asOf"), "value": x.get("value"),
                                   "unit": x.get("unit")} for x in (rows or drows)[-1300:]])})
    for mid, label in (("valuation.eps", "日経平均EPS"),
                       ("valuation.bps", "日経平均BPS"),
                       ("valuation.per18_level", "PER18倍水準"),
                       ("valuation.per21_level", "PER21倍水準(SHO参考上限)")):
        rows = metric_history.get(mid) or []
        cur, prev = (rows[-1] if rows else None), (rows[-2] if len(rows) > 1 else None)
        values = [x["value"] for x in rows if x.get("value") is not None]
        rank = (round(100 * sum(1 for x in values if x <= cur["value"]) / len(values), 1)
                if values and cur and cur.get("value") is not None else None)
        four_ago = rows[-5] if len(rows) >= 5 else None
        direction4 = (None if not cur or not four_ago or cur.get("value") is None
                      or four_ago.get("value") is None else
                      "up" if cur["value"] > four_ago["value"] else
                      "down" if cur["value"] < four_ago["value"] else "flat")
        table.append({"seriesId": mid, "labelJa": label,
                      "latestValue": cur.get("value") if cur else None,
                      "unit": "JPY",
                      "previousChange": (None if not cur or not prev
                                         or cur.get("value") is None or prev.get("value") is None
                                         else cur["value"] - prev["value"]),
                      "fourPeriodDirection": direction4,
                      "fourPeriodTotal": None, "consecutiveDirectionCount": None,
                      "thresholdDistance": None, "thresholdSide": None,
                      "thresholdStreak": None,
                      "historicalPercentile": rank,
                      "periodEnd": cur.get("asOf") if cur else None,
                      "availableFrom": None,
                      "status": cur.get("status") if cur else "missing",
                      "acquisition": "derived", "sourceKind": "derived",
                      "history": [{"periodEnd": x.get("asOf"), "value": x.get("value"),
                                   "unit": "JPY"} for x in rows[-1300:]]})
    def mv(mid: str): return (latest_metrics.get(mid) or {}).get("value")
    short = next((x for x in table if x["seriesId"] == "credit.short_balance"), {})
    long = next((x for x in table if x["seriesId"] == "credit.long_balance"), {})
    foreign = next((x for x in table if x["seriesId"] == "flow.foreign"), {})
    eps_rows = metric_history.get("valuation.eps") or []
    def metric_change(rows: List[Dict[str, Any]], lag: int) -> Optional[float]:
        if len(rows) <= lag or rows[-1].get("value") is None or rows[-1 - lag].get("value") is None:
            return None
        return round(rows[-1]["value"] - rows[-1 - lag]["value"], 2)
    eps_mom = metric_change(eps_rows, 1)
    eps_change_5 = metric_change(eps_rows, 5)
    eps_change_20 = metric_change(eps_rows, 20)
    per21_rows = metric_history.get("valuation.per21_level") or []
    per21_peak = max([x["value"] for x in per21_rows if x.get("value") is not None]
                     or [None])
    per21_current = (per21_rows[-1].get("value") if per21_rows else None)
    breadth25 = mv("breadth.prime.ratio25")
    if breadth25 is None:
        breadth25 = mv("breadth.ratio25")
    summary = {
        "shortFuel": "UNKNOWN" if short.get("latestValue") is None else "HIGH" if short["latestValue"] >= CREDIT_THRESHOLD_YEN else "LOW",
        "creditBuyingPressure": "UNKNOWN" if long.get("latestValue") is None else "HIGH" if (mv("credit.ratio") or 0) >= 4 else "NORMAL",
        "foreignFlow": "UNKNOWN" if foreign.get("latestValue") is None else "INFLOW" if foreign["latestValue"] > 0 else "OUTFLOW",
        "epsMomentum": "UNKNOWN" if eps_mom is None else "RISING" if eps_mom > 0 else "FALLING" if eps_mom < 0 else "FLAT",
        "valuationBand": ("UNKNOWN" if mv("valuation.eps") is None else
                          "HIGH_VALUATION_BAND" if (next((x.get("latestValue") for x in table
                                                          if x["seriesId"] == "valuation.per"), None) or 0) >= 18
                          else "NORMAL"),
        "breadth": "UNKNOWN" if breadth25 is None else "OVERHEAT_CANDIDATE" if breadth25 > 120 else "OVERSOLD_CANDIDATE" if breadth25 < 80 else "NEUTRAL",
    }
    return {"schemaVersion": SCHEMA_VERSION, "asOf": now_iso,
            "summary": summary, "table": table,
            "valuationSummary": {
                "epsPreviousChange": eps_mom, "eps5Change": eps_change_5,
                "eps20Change": eps_change_20,
                "per18Level": mv("valuation.per18_level"),
                "per21Level": per21_current, "per21RecentPeak": per21_peak,
                "per21ChangeFromPeak": (None if per21_current is None or per21_peak is None
                                        else round(per21_current - per21_peak, 2)),
                "labelJa": "PER21倍はSHO参考上限/高評価帯であり、絶対上限や目標株価ではありません。"},
            "flowCaveatJa": "海外と証券自己の反対売買は、配当期・裁定・ポジション移管等の可能性があり、フローの質は未確認です。",
            "breadthThresholdsJa": {"over120": "過熱候補", "under80": "売られすぎ候補"},
            "derivedMetrics": list(latest_metrics.values()),
            "turningPoints": [{**x, "subsequentOutcome": "not_evaluated"}
                               for x in st["turningPoints"][-200:]],
            "backtests": st["backtests"][-20:],
            "observationCount": len(st["observations"]),
            "stateHash": state_hash(st),
            "sourcePolicy": {sid: {"acquisition": d[2], "sourceKind": d[3]}
                             for sid, d in SERIES.items()},
            "noteJa": "市場全体データのみ。保有数量・取得価格を含まず、自動売買を行いません。"}


def read_back_verified(local: Dict[str, Any], remote: Dict[str, Any]) -> bool:
    return state_hash(local) == state_hash(remote)
