"""ARGUS — Downside Incident Response + Cause Attribution (pure, deterministic).

WHY (v10.98): on a sharp-drop day ARGUS only emitted generic "急落しています"
text and kept posture at HOLD/RISK_ON, which is a product failure for a holder.
This module turns a material drop into an *explained* incident: classification,
likely-cause buckets (probabilities that sum to 1), evidence/missing-data,
holder-specific action OVERRIDE (a large unexplained drop can never stay plain
HOLD), and a next-review condition. It also computes a JP intraday overlay so a
deteriorating Japan tape is not hidden behind a still-green US-ETF regime.

Hard product boundary (unchanged): decision SUPPORT only. Nothing here places
orders, sizes positions, or routes to a broker. "EXIT_WATCH"/"TRIM_WATCH" are
*watch* states for the owner to act on — never automatic actions.

Pure stdlib, no Flask, no network — so it is unit-testable in isolation. scanner
builds the context dicts from live snapshots and calls classify_incidents().
"""
from __future__ import annotations

# ── Vocabulary ──────────────────────────────────────────────────────────────
INCIDENT_TYPES = [
    "MARKET_WIDE_SELL_OFF",
    "SECTOR_SELL_OFF",
    "THEME_PROFIT_TAKING",
    "STOCK_SPECIFIC_BAD_NEWS",
    "FLOW_DISTRIBUTION",
    "SHORT_COVER_EXHAUSTION",
    "POST_RALLY_PROFIT_TAKING",
    "TECHNICAL_BREAKDOWN",
    "CAUSE_UNKNOWN_DOWNSIDE",
    "DATA_QUALITY_LIMITED",
]
# Causes the attribution matrix scores over (DATA_QUALITY_LIMITED is a status,
# not a cause — it short-circuits to a partial incident).
_CAUSES = [t for t in INCIDENT_TYPES if t != "DATA_QUALITY_LIMITED"]

SEVERITY_ORDER = ["low", "medium", "high", "critical"]
HOLDER_IMPACT_ORDER = ["none", "watch", "caution", "review_required", "trim_watch", "exit_watch"]
ACTION_OVERRIDES = ["HOLD_CAUTION", "WAIT", "DO_NOT_ADD", "REVIEW_REQUIRED", "TRIM_WATCH", "EXIT_WATCH"]

# ── Thresholds (single source of truth) ─────────────────────────────────────
DROP_WATCH = -3.0          # %: a watched/held JP name at/below this is an incident
DROP_SERIOUS = -5.0        # %: serious — overrides cannot remain plain HOLD
DROP_CRITICAL = -8.0       # %
HIGH_BETA_DROP = -4.0      # %: high-beta/momentum names trigger one notch sooner
GAP_DOWN = -3.0            # %: gap vs prev close
UNDERPERF_VS_INDEX = -2.0  # %: stock minus index
NIKKEI_RISK = -1.5         # %: JP index proxy intraday
NIKKEI_RISK_HARD = -2.5    # %
BREADTH_RISK = -1.0        # %: avg JP watchlist change
BREADTH_RISK_HARD = -2.5   # %
DECLINER_FRAC = 0.6        # share of JP names down → breadth risk
VOL_SURGE = 1.3            # volume / average


# ── small helpers ───────────────────────────────────────────────────────────
def _bump(level, order):
    i = order.index(level) if level in order else 0
    return order[min(i + 1, len(order) - 1)]


def _max_level(a, b, order):
    return a if order.index(a) >= order.index(b) else b


def _num(x):
    return x if isinstance(x, (int, float)) and x == x else None  # rejects NaN


def _rally_strength(a):
    """0..3 — how extended the prior move was (drives profit-taking causes)."""
    s = 0
    for k, thr in (("ret3d", 6.0), ("ret5d", 10.0), ("ret20d", 20.0)):
        v = _num(a.get(k))
        if v is not None and v >= thr:
            s += 1
    return s


def _flow_outflow(a):
    fr = _num(a.get("flowRatio"))
    return fr is not None and fr < 0


def _flow_turned_outflow(a):
    fr, pr = _num(a.get("flowRatio")), _num(a.get("priorFlowRatio"))
    return fr is not None and pr is not None and pr > 0 and fr < 0


# ── Cause attribution matrix ────────────────────────────────────────────────
def cause_scores(a, m):
    """Raw (un-normalized) evidence scores per cause. Deterministic."""
    s = {c: 0.0 for c in _CAUSES}
    drop = _num(a.get("changePct")) or 0.0
    mag = abs(drop)
    rally = _rally_strength(a)

    # MARKET_WIDE_SELL_OFF
    mw = 0.0
    nik = _num(m.get("nikkeiProxyPct"))
    if nik is not None and nik <= NIKKEI_RISK:
        mw += 1.6
    if nik is not None and nik <= NIKKEI_RISK_HARD:
        mw += 1.0
    br = _num(m.get("jpBreadth"))
    if br is not None and br <= BREADTH_RISK:
        mw += 1.0
    dec, tot = m.get("jpDecliners"), m.get("jpTotal")
    if dec and tot and tot > 0 and dec / tot >= DECLINER_FRAC:
        mw += 1.0
    if m.get("vixStress") or m.get("ratesStress"):
        mw += 1.0
    if m.get("globalRegime") in ("RISK_OFF", "CAUTIOUS"):
        mw += 0.5
    s["MARKET_WIDE_SELL_OFF"] = mw

    # SECTOR / THEME — split into profit-taking vs plain sector selloff
    if a.get("themePeersDown"):
        if rally >= 1:
            s["THEME_PROFIT_TAKING"] += 1.8 + rally * 0.6
        else:
            s["SECTOR_SELL_OFF"] += 1.8
    if a.get("sectorWeak"):
        s["SECTOR_SELL_OFF"] += 0.8

    # STOCK_SPECIFIC_BAD_NEWS — needs a confirmed catalyst (no guessing)
    ss = 0.0
    if a.get("catalyst"):
        ss += 2.6
    vi = _num(a.get("vsIndexPct"))
    if vi is not None and vi <= UNDERPERF_VS_INDEX:
        ss += 1.0
    s["STOCK_SPECIFIC_BAD_NEWS"] = ss

    # POST_RALLY_PROFIT_TAKING
    pt = 0.0
    if rally >= 1 and not a.get("catalyst"):
        pt += 1.0 + rally * 0.7
    if _flow_turned_outflow(a):
        pt += 0.6
    if m.get("highBetaDown"):
        pt += 0.3
    s["POST_RALLY_PROFIT_TAKING"] += pt

    # FLOW_DISTRIBUTION — price weak with negative big-money flow
    ds = 0.0
    if _flow_outflow(a):
        ds += 1.6
        vr = _num(a.get("volRatio"))
        if vr is not None and vr >= VOL_SURGE:
            ds += 0.8
        if a.get("weakClose"):
            ds += 0.7
        if a.get("failedRecovery"):
            ds += 0.5
    s["FLOW_DISTRIBUTION"] = ds

    # SHORT_COVER_EXHAUSTION
    if a.get("priorSqueeze") and rally >= 1 and not a.get("catalyst"):
        sc = 1.4
        if _num(a.get("flowRatio")) is not None and _num(a.get("flowRatio")) <= 0.05:
            sc += 0.6
        s["SHORT_COVER_EXHAUSTION"] = sc

    # TECHNICAL_BREAKDOWN
    tb = 0.0
    if a.get("limitProximity"):
        tb += 0.9
    if a.get("accelDown"):
        tb += 0.9
    s["TECHNICAL_BREAKDOWN"] = tb

    # CAUSE_UNKNOWN_DOWNSIDE — NOT neutral. High when evidence is thin. A bigger
    # unexplained drop raises caution, never lowers it.
    known = sum(s.values())
    unk = 0.0
    if a.get("catalyst") is None and a.get("newsChecked"):
        unk += 1.0                          # checked, found nothing → genuine unknown
    if known < 1.0:
        unk += 1.6
    if not a.get("dataFreshnessOk", True) or m.get("dataPartial"):
        unk += 0.6
    unk += min(mag / 5.0, 1.5)              # scales with drop size
    s["CAUSE_UNKNOWN_DOWNSIDE"] = unk
    return s


def cause_buckets(a, m):
    """Normalized probability buckets (sum to 1.0), sorted desc."""
    raw = cause_scores(a, m)
    total = sum(raw.values())
    if total <= 0:
        return [{"cause": "CAUSE_UNKNOWN_DOWNSIDE", "probability": 1.0, "evidenceIds": []}]
    buckets = [{"cause": c, "probability": v / total, "evidenceIds": []}
               for c, v in raw.items() if v > 0]
    buckets.sort(key=lambda b: b["probability"], reverse=True)
    # round to 2dp but keep the sum exactly 1.0 by adjusting the top bucket
    for b in buckets:
        b["probability"] = round(b["probability"], 2)
    drift = round(1.0 - sum(b["probability"] for b in buckets), 2)
    if buckets and abs(drift) >= 0.01:
        buckets[0]["probability"] = round(buckets[0]["probability"] + drift, 2)
    return buckets


# ── Severity / override ─────────────────────────────────────────────────────
def _severity(a, top_cause):
    mag = abs(_num(a.get("changePct")) or 0.0)
    sev = "low"
    if mag >= abs(DROP_WATCH):
        sev = "medium"
    if mag >= abs(DROP_SERIOUS):
        sev = "high"
    if mag >= abs(DROP_CRITICAL):
        sev = "critical"
    if a.get("beta") == "high" and mag >= abs(HIGH_BETA_DROP) and sev == "medium":
        sev = "high"
    if top_cause == "STOCK_SPECIFIC_BAD_NEWS" and mag >= abs(DROP_SERIOUS):
        sev = _bump(sev, SEVERITY_ORDER)
    if _held_like(a):                         # held/protected carry more risk than watchers
        sev = _bump(sev, SEVERITY_ORDER)
    if a.get("ownerState") == "protected":    # protected = one extra notch
        sev = _bump(sev, SEVERITY_ORDER)
    if a.get("downsideStrictness") == "strict":
        sev = _bump(sev, SEVERITY_ORDER)
    return sev


def _held_like(a):
    return bool(a.get("isHeld")) or a.get("ownerState") in ("held", "protected")


def _override(a, top_cause, sev):
    mag = abs(_num(a.get("changePct")) or 0.0)
    fr = _num(a.get("flowRatio"))
    override, impact = "HOLD_CAUTION", "watch"

    if top_cause == "MARKET_WIDE_SELL_OFF":
        override, impact = ("WAIT", "caution") if mag >= abs(DROP_WATCH) else ("HOLD_CAUTION", "watch")
    elif top_cause == "STOCK_SPECIFIC_BAD_NEWS":
        if sev == "critical":
            override, impact = "EXIT_WATCH", "exit_watch"
        elif sev == "high":
            override, impact = "TRIM_WATCH", "trim_watch"
        else:
            override, impact = "REVIEW_REQUIRED", "review_required"
    elif top_cause in ("POST_RALLY_PROFIT_TAKING", "THEME_PROFIT_TAKING"):
        override, impact = ("WAIT", "caution") if mag >= abs(DROP_SERIOUS) else ("HOLD_CAUTION", "caution")
    elif top_cause == "FLOW_DISTRIBUTION":
        override, impact = ("TRIM_WATCH", "trim_watch") if mag >= abs(DROP_SERIOUS) else ("REVIEW_REQUIRED", "review_required")
    elif top_cause == "SHORT_COVER_EXHAUSTION":
        override, impact = "HOLD_CAUTION", "caution"
    elif top_cause == "TECHNICAL_BREAKDOWN":
        override, impact = "WAIT", "caution"
    elif top_cause == "CAUSE_UNKNOWN_DOWNSIDE":
        if mag >= abs(DROP_SERIOUS):
            override, impact = "REVIEW_REQUIRED", "review_required"
        else:
            override, impact = "DO_NOT_ADD", "caution"

    # Strong positive flow + no confirmed catalyst → still not plain HOLD, but the
    # mildest override (HOLD_CAUTION) is justified.
    if fr is not None and fr > 0.1 and not a.get("catalyst") and override == "WAIT" \
            and top_cause in ("POST_RALLY_PROFIT_TAKING", "THEME_PROFIT_TAKING"):
        override = "HOLD_CAUTION"

    # A serious drop must never remain plain HOLD (acceptance criterion).
    if mag >= abs(DROP_SERIOUS) and override == "HOLD_CAUTION":
        override, impact = "REVIEW_REQUIRED", _max_level(impact, "review_required", HOLDER_IMPACT_ORDER)

    # Held/protected/strict: a real drop (>= watch threshold) cannot sit at the
    # mildest override — escalate HOLD_CAUTION to REVIEW_REQUIRED so a position
    # the owner actually holds is never quietly treated as plain HOLD.
    strict = a.get("downsideStrictness") == "strict" or a.get("ownerState") == "protected"
    if (_held_like(a) or strict) and override == "HOLD_CAUTION" and mag >= abs(DROP_WATCH):
        override = "REVIEW_REQUIRED"
        impact = _max_level(impact, "review_required", HOLDER_IMPACT_ORDER)

    if _held_like(a):                         # held/protected get one notch stricter impact
        impact = _bump(impact, HOLDER_IMPACT_ORDER)
    return override, impact


# ── Trigger gate ────────────────────────────────────────────────────────────
def should_trigger(a, m=None):
    """True if this asset's drop is material enough to warrant an incident."""
    m = m or {}
    drop = _num(a.get("changePct"))
    if drop is None:
        return False
    if drop <= DROP_WATCH:
        return True
    if a.get("beta") == "high" and drop <= HIGH_BETA_DROP:
        return True
    gap = _num(a.get("gapDownPct"))
    if gap is not None and gap <= GAP_DOWN:
        return True
    if a.get("accelDown"):
        return True
    if _flow_turned_outflow(a) and drop < 0:
        return True
    vi = _num(a.get("vsIndexPct"))
    if vi is not None and vi <= UNDERPERF_VS_INDEX and drop < 0:
        return True
    # A holder in a market-wide selloff still wants a (milder) incident.
    if a.get("isHeld") and drop < -1.5 and _market_wide(m):
        return True
    return False


def _market_wide(m):
    nik = _num(m.get("nikkeiProxyPct"))
    br = _num(m.get("jpBreadth"))
    dec, tot = m.get("jpDecliners"), m.get("jpTotal")
    return bool(
        (nik is not None and nik <= NIKKEI_RISK)
        or (br is not None and br <= BREADTH_RISK_HARD)
        or (dec and tot and tot > 0 and dec / tot >= DECLINER_FRAC)
    )


# ── Text builders (Japanese reasoning, English chrome) ──────────────────────
_CAUSE_JA = {
    "MARKET_WIDE_SELL_OFF": "市場全体の下げ(地合い悪化)",
    "SECTOR_SELL_OFF": "セクター全体の下げ",
    "THEME_PROFIT_TAKING": "テーマ全体の利益確定売り",
    "STOCK_SPECIFIC_BAD_NEWS": "個別の材料(悪材料の可能性・要確認)",
    "FLOW_DISTRIBUTION": "大口の売り(ディストリビューション)疑い",
    "SHORT_COVER_EXHAUSTION": "踏み上げ一巡(買い戻し枯れ)疑い",
    "POST_RALLY_PROFIT_TAKING": "急騰後の利益確定売り",
    "TECHNICAL_BREAKDOWN": "テクニカルな崩れ",
    "CAUSE_UNKNOWN_DOWNSIDE": "原因未確認の下落",
    "DATA_QUALITY_LIMITED": "データ不足で原因特定不可",
}
_DONOT_JA = {
    "REVIEW_REQUIRED": "原因が確認できるまで買い増し禁止。通常のHOLDとして扱わない。",
    "DO_NOT_ADD": "押し目買いの根拠が不十分。新規の買い増しは控える。",
    "WAIT": "買い増し禁止。地合い/原因の確認まで新規追加しない。",
    "TRIM_WATCH": "買い増し禁止。戻りでの一部利確/縮小も選択肢として点検。",
    "EXIT_WATCH": "買い増し禁止。撤退を含めて要点検(ただし自動売却はしない・本人判断)。",
    "HOLD_CAUTION": "高値追い・狼狽売りの両方を避ける。新規の積み増しは慎重に。",
}


def _missing_data(a):
    md = []
    if a.get("market") == "JP" and not a.get("tdnetConnected"):
        md.append("TDnet未接続のため、業績修正・自社株買い・決算短信などの即時確認に限界。")
    if not a.get("newsChecked"):
        md.append("ニュース/材料ソース未取得。")
    elif a.get("catalyst") is None:
        md.append("現時点で公式悪材料は未確認(=安全の証明ではない)。")
    if _num(a.get("flowRatio")) is None:
        md.append("大口フロー(moomooブリッジ)未取得。")
    if not a.get("dataFreshnessOk", True):
        md.append("価格データの鮮度が低い(遅延の可能性)。")
    return md


def _reason_ja(a, top_cause, buckets, sev):
    mag = abs(_num(a.get("changePct")) or 0.0)
    name = a.get("assetName") or a.get("name") or a.get("symbol")
    lead = f"{name}が{_num(a.get('changePct')):.1f}%。"
    body = _CAUSE_JA.get(top_cause, "下落")
    if len(buckets) >= 2 and buckets[1]["probability"] >= 0.25:
        body += f"(次点: {_CAUSE_JA.get(buckets[1]['cause'], buckets[1]['cause'])})"
    tail = ""
    if top_cause == "CAUSE_UNKNOWN_DOWNSIDE":
        tail = " 公式の悪材料は確認できず、原因不明の下げのため警戒を引き上げる。"
    elif top_cause == "MARKET_WIDE_SELL_OFF":
        tail = " 個別要因より地合い主導。"
    elif top_cause in ("THEME_PROFIT_TAKING", "POST_RALLY_PROFIT_TAKING"):
        tail = " 急騰の反動の色が濃い。"
    elif top_cause == "FLOW_DISTRIBUTION":
        tail = " 大口の流出を伴っており、戻りの弱さに注意。"
    elif top_cause == "STOCK_SPECIFIC_BAD_NEWS":
        cat = a.get("catalyst") if isinstance(a.get("catalyst"), dict) else {}
        if cat.get("confirmedNegative"):
            tail = " 個別の悪材料が確認されている。"
        elif cat.get("detail"):
            tail = f" 直近に個別材料({cat['detail']})があり下落と整合(内容は要確認・悪材料と断定はしない)。"
        else:
            tail = " 個別の材料が示唆される(要確認)。"
    held = " 保有銘柄のため判定を一段厳しめに適用。" if a.get("isHeld") else ""
    return lead + body + "の可能性。" + tail + held


def _next_condition_ja(top_cause):
    return {
        "MARKET_WIDE_SELL_OFF": "Nikkei/TOPIXの下げ止まり・地合いの安定を確認できれば見直し。",
        "FLOW_DISTRIBUTION": "大口フローの反転(流出→流入)と引けにかけての戻りを確認。",
        "THEME_PROFIT_TAKING": "テーマ銘柄群の下げ止まりとVWAP/引け値の回復を確認。",
        "POST_RALLY_PROFIT_TAKING": "VWAP回復・引け値の安定、押し目の出来高で再評価。",
        "STOCK_SPECIFIC_BAD_NEWS": "材料の織り込み完了(続落の有無)と公式続報を確認。",
        "CAUSE_UNKNOWN_DOWNSIDE": "原因(ニュース/開示/大口フロー)の特定、または引けでの下げ止まりを確認。",
        "SHORT_COVER_EXHAUSTION": "新規の買い手の出現と出来高を伴う反発を確認。",
        "TECHNICAL_BREAKDOWN": "直近の節目の回復と売り圧力の一巡を確認。",
    }.get(top_cause, "原因の特定または下げ止まりを確認。")


# ── Main per-asset classifier ───────────────────────────────────────────────
def classify_incident(a, m=None, now_iso=None):
    """Return an incident dict for asset-context `a`, or None if not triggered.

    `a` keys (all optional unless noted): symbol(req), market, name/assetName,
    changePct(req), price, prevClose, flowRatio, priorFlowRatio, ret3d/ret5d/
    ret20d, beta('high'), gapDownPct, volRatio, weakClose, failedRecovery,
    accelDown, limitProximity, vsIndexPct, catalyst(dict|None), newsChecked,
    tdnetConnected, isHeld, themePeersDown, sectorWeak, priorSqueeze,
    dataFreshnessOk, currentAction.
    `m` = market context (see _market_wide / cause_scores).
    """
    m = m or {}
    if not should_trigger(a, m):
        return None

    sym = a.get("symbol") or "?"
    market = a.get("market") or "JP"
    name = a.get("assetName") or a.get("name") or sym
    change = _num(a.get("changePct"))

    # Data-quality short-circuit: too little to attribute → partial incident.
    partial = bool(m.get("dataPartial")) or not a.get("dataFreshnessOk", True)
    very_limited = (_num(a.get("flowRatio")) is None and not a.get("newsChecked")
                    and not _market_wide(m))

    buckets = cause_buckets(a, m)
    top_cause = buckets[0]["cause"]
    sev = _severity(a, top_cause)
    override, impact = _override(a, top_cause, sev)

    incident_type = top_cause
    if very_limited and top_cause == "CAUSE_UNKNOWN_DOWNSIDE":
        incident_type = "DATA_QUALITY_LIMITED"

    inc = {
        "incidentId": f"{market}:{sym}:{incident_type}",
        "symbol": sym,
        "market": market,
        "assetName": name,
        "changePct": round(change, 2) if change is not None else None,
        "incidentType": incident_type,
        "severity": sev,
        "holderImpact": impact,
        "currentAction": a.get("currentAction") or "HOLD",
        "actionOverride": override,
        "causeBuckets": buckets,
        "reasonJa": _reason_ja(a, top_cause, buckets, sev),
        "missingData": _missing_data(a),
        "nextConditionJa": _next_condition_ja(top_cause),
        "doNotDoJa": _DONOT_JA.get(override, "新規の買い増しは控える。"),
        "nextReviewAt": now_iso,
        "isHeld": _held_like(a),
        "ownerState": a.get("ownerState") or ("held" if a.get("isHeld") else "watch"),
        "priority": a.get("priority") or "normal",
        "status": "partial" if partial else "live",
    }
    inc["dedupKey"] = incident_dedup_key(inc, a, m)
    return inc


def classify_incidents(assets, m=None, now_iso=None):
    """Classify a list of asset contexts; return triggered incidents sorted by
    severity then holder-impact then drop size (most urgent first)."""
    m = m or {}
    out = []
    for a in assets or []:
        inc = classify_incident(a, m, now_iso)
        if inc:
            out.append(inc)
    out.sort(key=lambda i: (
        -SEVERITY_ORDER.index(i["severity"]),
        -HOLDER_IMPACT_ORDER.index(i["holderImpact"]),
        i.get("changePct") if i.get("changePct") is not None else 0.0,
    ))
    return out


# ── JP intraday regime overlay ──────────────────────────────────────────────
def jp_intraday_overlay(m):
    """Do NOT collapse a green global (US-ETF) regime onto a weak Japan tape.
    Returns globalRegime + jpIntradayOverlay + holderRiskOverlay (+ flags)."""
    m = m or {}
    glob = m.get("globalRegime") or "UNKNOWN"
    nik = _num(m.get("nikkeiProxyPct"))
    br = _num(m.get("jpBreadth"))
    dec, tot = m.get("jpDecliners"), m.get("jpTotal")
    flags = []
    overlay = "NORMAL"

    if nik is not None and nik <= NIKKEI_RISK:
        flags.append("JP_BREADTH_RISK")
        overlay = "CAUTION"
    if dec and tot and tot > 0 and dec / tot >= DECLINER_FRAC:
        if "JP_BREADTH_RISK" not in flags:
            flags.append("JP_BREADTH_RISK")
        overlay = _max_overlay(overlay, "CAUTION")
    if m.get("highBetaDown"):
        flags.append("JP_HIGH_BETA_SELL_OFF")
        overlay = _max_overlay(overlay, "CAUTION")
    if m.get("themeUnwind"):
        flags.append("JP_THEME_UNWIND")
        overlay = _max_overlay(overlay, "CAUTION")
    if m.get("profitTakingDay"):
        flags.append("JP_PROFIT_TAKING_DAY")
    if (nik is not None and nik <= NIKKEI_RISK_HARD) or (br is not None and br <= BREADTH_RISK_HARD):
        overlay = "RISK_OFF_WATCH"

    # Escalate on actual severe incidents — a few crashing names must NOT be hidden
    # by a near-zero *average* breadth (the same masking problem, at index level).
    severe = int(m.get("jpSevereIncidents") or 0)     # high+critical JP incidents
    critical = int(m.get("jpCriticalIncidents") or 0)
    if severe >= 1 or critical >= 1:
        flags.append("JP_HIGH_BETA_SELL_OFF") if "JP_HIGH_BETA_SELL_OFF" not in flags else None
        overlay = _max_overlay(overlay, "CAUTION")
    if severe >= 3 or critical >= 2:
        overlay = "RISK_OFF_WATCH"

    holder_overlay = ("REVIEW_REQUIRED"
                      if (m.get("ownerAffected") or m.get("ownerSevereAffected")) and overlay != "NORMAL"
                      else "NONE")

    if overlay == "NORMAL":
        display = f"Global regime: {glob}"
        reason = "日本市場の地合いに大きな崩れは確認されていない。"
    else:
        display = f"Global regime: {glob}, JP intraday overlay: {overlay}"
        reason = ("米ETF基準の地合いは" + str(glob) + "だが、日本市場(指数/breadth/高ベータ)は"
                  + ("警戒" if overlay == "CAUTION" else "リスクオフ寄り")
                  + "。グローバルとJPを混同せず、JPは別レンズで見る。")

    return {
        "globalRegime": glob,
        "jpIntradayOverlay": overlay,
        "holderRiskOverlay": holder_overlay,
        "flags": flags,
        "displayJa": display,
        "reasonJa": reason,
    }


def _max_overlay(a, b):
    order = ["NORMAL", "CAUTION", "RISK_OFF_WATCH"]
    return a if order.index(a) >= order.index(b) else b


# ── Notification ────────────────────────────────────────────────────────────
_OVERRIDE_JA = {
    "HOLD_CAUTION": "HOLD(警戒)", "WAIT": "WAIT(待機)", "DO_NOT_ADD": "買い増し禁止",
    "REVIEW_REQUIRED": "REVIEW REQUIRED(要点検)", "TRIM_WATCH": "TRIM WATCH(縮小検討)",
    "EXIT_WATCH": "EXIT WATCH(撤退検討)",
}


# Downside override → Action Level (mirror of domain/actionLevel.ts, v10.121):
# (level, EN label, JA label). All downside levels BLOCK new entry + add.
_ACTION_LEVEL = {
    "EXIT_WATCH": (2, "DEFEND", "防御"), "TRIM_WATCH": (2, "DEFEND", "防御"),
    "REVIEW_REQUIRED": (3, "REVIEW", "再点検"), "DO_NOT_ADD": (3, "REVIEW", "再点検"),
    "HOLD_CAUTION": (5, "HOLD ONLY", "保有のみ"), "WAIT": (4, "PAUSE", "保留"),
}


def build_notification(inc, locale="ja"):
    """Action-Level notification (v10.121) — never a bare "急落". Shows the level,
    explicit BLOCKED permissions, cause, and next condition, in the chosen locale."""
    pct = inc.get("changePct")
    pct_s = f"{pct:+.1f}%" if isinstance(pct, (int, float)) else ("downside" if locale == "en" else "下落")
    level, label_en, label_ja = _ACTION_LEVEL.get(inc.get("actionOverride"), (3, "REVIEW", "再点検"))
    cause = _CAUSE_JA.get(inc.get("incidentType"), "下落")
    held = ("[HELD] " if locale == "en" else "【保有】") if inc.get("isHeld") else ""
    title = f"{held}{inc.get('symbol')} {inc.get('assetName')} {pct_s}".strip()
    if locale == "en":
        msg = (f"ACTION {level}/7 — {label_en}\nNEW ENTRY: BLOCKED · ADD: BLOCKED\n"
               f"Cause: {cause}\nNext: {inc.get('nextConditionJa')}")
    else:
        msg = (f"アクション {level}/7 — {label_ja}\n新規購入: 禁止 · 買い増し: 禁止\n"
               f"原因: {cause}\n次: {inc.get('nextConditionJa')}")
    return {"title": title, "message": msg, "actionLevel": level, "signalLabel": label_en,
            "priority": "high" if inc.get("severity") in ("high", "critical") else "default"}


# ── Dedup: only re-notify on a material change ──────────────────────────────
def incident_dedup_key(inc, a=None, m=None):
    """Stable signature; changes only on a *material* change (severity, cause,
    override, confirmed catalyst, flow sign, market-breadth bucket)."""
    a = a or {}
    m = m or {}
    fr = _num(a.get("flowRatio"))
    flow_sign = "0" if fr is None else ("neg" if fr < 0 else "pos")
    catalyst = "cat" if a.get("catalyst") else "nocat"
    breadth = "mw" if _market_wide(m) else "iso"
    return "|".join([
        inc.get("symbol", "?"), inc.get("incidentType", "?"),
        inc.get("severity", "?"), inc.get("actionOverride", "?"),
        catalyst, flow_sign, breadth,
    ])


def is_material_change(prev_key, new_key):
    """True if the incident changed enough to justify a fresh notification."""
    return prev_key != new_key
