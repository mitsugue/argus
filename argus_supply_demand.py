"""ARGUS V11.10.0 — Supply / Demand Intelligence Layer (pure, deterministic).

The owner's question is never 「貸借倍率は0.42か」 — it is 「需給は良いのか悪い
のか」「踏み上げ余地はあるのか」「信用買い残が重くて上値が抑えられるのか」.
This module reads margin/loan/short structure and answers as a RANK + STATE in
plain Japanese. Raw numbers are evidence, never the primary UX.

HARD RULES:
  - Never fabricate JSF/margin/short/逆日歩 numbers. Missing = missingEvidence
    + lower confidence + 「暫定」 wording.
  - A short-covering shaped rise is NEVER called new institutional buying:
    「買い戻し主導の可能性があり、新規の大口買いとは未確定」.
  - actionImplication is a risk posture (monitor/wait/avoid_chase/
    add_only_on_pullback/investigate/caution/no_action) — never a trade order.
  - S rank requires DIRECT data; inference alone can never mint an S.

Terminology (kept consistent with the data feeds):
  - 週次信用残 (J-Quants margin-interest): marginBuyingBalance=LongVol(買い残),
    marginSellingBalance=ShrtVol(売り残).
  - JSF 貸借取引残高: loanBalance=融資残(買い方), lendingBalance=貸株残(売り方).
    貸借倍率 lendingBorrowingRatio = 融資残 / 貸株残. <1 = 売り長.
  - 逆日歩 (reverseStockLendingFee): NOT ingested yet — always reported as
    unavailable, never invented.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "supply-demand-v1"

RANKS = ("S", "A", "B", "C", "D", "E", "Unknown")
CONDITIONS = ("very_good", "good", "slightly_good", "neutral", "deteriorating", "bad",
              "squeeze_prone", "credit_overhang", "improving_but_heavy",
              "distribution_risk", "liquidity_thin", "mixed", "unknown")
LEVELS = ("light", "normal", "heavy", "very_heavy", "unknown")
LEVEL_JA = {"light": "軽い", "normal": "普通", "heavy": "まだ重い",
            "very_heavy": "かなり重い", "unknown": "不明"}
DIRECTIONS = ("improving", "worsening", "stable", "mixed", "unknown")
ACTIONS = ("monitor", "wait", "avoid_chase", "add_only_on_pullback",
           "investigate", "caution", "no_action")
DIRECTNESS = ("direct_data", "inferred", "weak_context", "insufficient")

RANK_JA = {
    "S": "非常に良い(直接データ裏付け)", "A": "良い", "B": "やや良い/注目",
    "C": "中立・混在", "D": "弱い・注意", "E": "悪い・追いかけ買い回避",
    "Unknown": "判定保留(データ不足)",
}
CONDITION_JA = {
    "very_good": "需給非常に良好", "good": "需給良好", "slightly_good": "需給やや良好",
    "neutral": "中立", "deteriorating": "需給悪化中", "bad": "需給悪い",
    "squeeze_prone": "踏み上げ注意(売り長)", "credit_overhang": "信用買い残重い",
    "improving_but_heavy": "改善中だが信用買い残はまだ重い",
    "distribution_risk": "戻り売り注意", "liquidity_thin": "薄商い注意",
    "mixed": "強弱混在", "unknown": "判定保留",
}
# condition chips (UI badges) — short, honest, Japanese
CONDITION_CHIPS = {
    "squeeze_prone": ["踏み上げ注意", "買い戻し主導"],
    "credit_overhang": ["信用買い残重い", "戻り売り注意"],
    "improving_but_heavy": ["需給改善方向", "信用買い残重い"],
    "distribution_risk": ["戻り売り注意"],
    "very_good": ["需給改善"], "good": ["需給改善"], "slightly_good": ["需給改善"],
    "deteriorating": ["需給悪化"], "bad": ["需給悪化"],
    "liquidity_thin": ["薄商い注意"],
    "mixed": [], "neutral": [], "unknown": ["判定保留"],
}
ACTION_JA = {"monitor": "監視継続", "wait": "確認待ち", "avoid_chase": "追いかけ買い注意",
             "add_only_on_pullback": "買うなら押し目限定", "investigate": "要調査",
             "caution": "警戒", "no_action": "対応不要"}
DIRECTNESS_JA = {"direct_data": "実データ(信用/貸借)あり", "inferred": "値動きからの推定",
                 "weak_context": "弱い状況証拠", "insufficient": "データ不足"}

EVIDENCE_KEYS = ("marginBuyingBalance", "marginSellingBalance", "marginBalanceChange",
                 "lendingBalance", "borrowingBalance", "loanBalance",
                 "lendingBorrowingRatio", "shortSellingRatio", "reverseStockLendingFee",
                 "daysToCover", "measuredFlowNetRatio", "volumeTrend", "turnoverTrend", "priceActionContext",
                 "closeLocation", "gapFadeFlag", "institutionalContext",
                 "flowAttributionContext", "eventContext")


def _f(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def classify(symbol: str, market: str, ev: Dict[str, Any], now_iso: str) -> Dict[str, Any]:
    """Evidence dict → SupplyDemandSignal. Deterministic. Expected evidence
    (ALL optional — absence is an honest gap, never guessed):
      marginBuying, marginSelling, marginBuyingPrev, marginSellingPrev, marginDate,
      jsfLoan, jsfLending, jsfDate, avgDailyVolume, volumeRatio, changePct,
      priorRunupPct, closeLocation, gapFade, liquidityLow, flowClass, instStance,
      eventToday, regimeRiskOff, sources{jqMargin,jsf,shortRatio}
    """
    is_us = str(market).upper() == "US"
    mb, ms = _f(ev.get("marginBuying")), _f(ev.get("marginSelling"))
    mb_prev, ms_prev = _f(ev.get("marginBuyingPrev")), _f(ev.get("marginSellingPrev"))
    loan, lend = _f(ev.get("jsfLoan")), _f(ev.get("jsfLending"))
    avg_vol = _f(ev.get("avgDailyVolume"))
    vr, chg = _f(ev.get("volumeRatio")), _f(ev.get("changePct"))
    runup = _f(ev.get("priorRunupPct"))
    measured_flow = _f(ev.get("measuredFlowNetRatio"))   # US bridge big-money net ratio
    flow_class = ev.get("flowClass")
    missing: List[str] = []
    evidence: Dict[str, Any] = {k: None for k in EVIDENCE_KEYS}

    has_margin = mb is not None or ms is not None
    has_jsf = loan is not None or lend is not None
    # v11.11.0 US支援(オーナー質問「アメリカ株の需給はわからないのかな」への正直な
    # 答え): 米国には信用残/日証金に相当する公開日次データが無い。代わりに実測の
    # 大口資金フロー(ブリッジ)を直接証拠として使い、squeeze/信用過多系は
    # 「判定不能(データ未取込)」を貫く — JPと同じ見た目・違う限界を明示する。
    has_us_flow = is_us and measured_flow is not None
    direct = has_margin or has_jsf or has_us_flow
    if is_us:
        missing.append("FINRA空売り残(隔週・未取込)")
        missing.append("貸株フィー(未取込)")
        if not has_us_flow:
            missing.append("実測大口フロー(ブリッジ)")
    else:
        if not has_margin:
            missing.append("週次信用残(J-Quants)")
        if not has_jsf:
            missing.append("日証金貸借残")
        missing.append("逆日歩(未取込ソース)")       # never ingested yet — always honest
    if avg_vol is None:
        missing.append("平均出来高")
    if ev.get("closeLocation") is None:
        missing.append("日中の終値位置")

    # ── derived structure numbers (only from real inputs) ───────────────────
    ratio = None                                      # 貸借倍率 (JSF preferred)
    if loan is not None and lend and lend > 0:
        ratio = round(loan / lend, 2)
    elif mb is not None and ms and ms > 0:
        ratio = round(mb / ms, 2)
    uri_naga = (ratio is not None and ratio < 1.0)    # 売り長
    days_to_cover = (round(ms / avg_vol, 1)
                     if ms is not None and avg_vol and avg_vol > 0 else None)
    buy_overhang_days = (round(mb / avg_vol, 1)
                         if mb is not None and avg_vol and avg_vol > 0 else None)
    mb_chg = (round((mb - mb_prev) / mb_prev * 100, 1)
              if mb is not None and mb_prev and mb_prev > 0 else None)
    ms_chg = (round((ms - ms_prev) / ms_prev * 100, 1)
              if ms is not None and ms_prev and ms_prev > 0 else None)

    # ── v11.14.0 (owner: フジクラA問題): LEVEL is separate from DIRECTION.
    # 「買い残が前週比で減った」は改善方向であって「需給良好」ではない。
    # level = 信用倍率(買い残/売り残)と買い残の出来高日数の“悪い方”。
    margin_ratio = (round(mb / ms, 2) if mb is not None and ms and ms > 0 else None)
    def _lv_days(d):
        if d is None:
            return None
        return ("light" if d < 2 else "normal" if d < 5 else
                "heavy" if d < 10 else "very_heavy")
    def _lv_ratio(rt):
        if rt is None:
            return None
        return ("light" if rt <= 2 else "normal" if rt <= 5 else
                "heavy" if rt <= 10 else "very_heavy")
    _sev = {"light": 0, "normal": 1, "heavy": 2, "very_heavy": 3}
    _cands = [x for x in (_lv_days(buy_overhang_days), _lv_ratio(margin_ratio)) if x]
    level = max(_cands, key=lambda x: _sev[x]) if _cands else "unknown"
    improving_dir = (mb_chg is not None and mb_chg < 0)

    # evidence block (raw numbers live HERE — the UI hides them behind 詳細)
    evidence.update({
        "marginBuyingBalance": mb, "marginSellingBalance": ms,
        "marginBalanceChange": ({"buyPct": mb_chg, "sellPct": ms_chg}
                                if (mb_chg is not None or ms_chg is not None) else None),
        "loanBalance": loan, "lendingBalance": lend,
        "lendingBorrowingRatio": ratio,
        "shortSellingRatio": _f(ev.get("shortSellingRatio")),
        "reverseStockLendingFee": None,               # not ingested — never invented
        "daysToCover": days_to_cover,
        "measuredFlowNetRatio": measured_flow,
        "volumeTrend": (f"出来高比 {vr:.1f}倍" if vr is not None else None),
        "turnoverTrend": None,
        "priceActionContext": (f"変化率{chg:+.1f}%" + (f"・直近{runup:+.0f}%"
                               if runup is not None else "") if chg is not None else None),
        "closeLocation": _f(ev.get("closeLocation")),
        "gapFadeFlag": bool(ev.get("gapFade")) if ev.get("gapFade") is not None else None,
        "institutionalContext": ev.get("instStance"),
        "flowAttributionContext": flow_class,
        "eventContext": ("本日イベントあり" if ev.get("eventToday") else None),
    })

    # ── deterministic condition scoring (max wins; ties → mixed) ────────────
    scores: Dict[str, float] = {}
    up = chg is not None and chg > 0
    down = chg is not None and chg < 0
    vol_up = vr is not None and vr >= 1.3

    if ev.get("liquidityLow"):
        scores["liquidity_thin"] = 0.5

    # ── US branch: measured big-money flow IS the direct evidence ───────────
    if has_us_flow:
        if measured_flow > 0.12 and up:
            scores["good"] = 0.5 + (0.1 if vol_up else 0.0)
        elif measured_flow > 0.12:
            scores["slightly_good"] = 0.45
        elif measured_flow < -0.12 and up:
            scores["distribution_risk"] = 0.55        # selling into strength
        elif measured_flow < -0.12 and down:
            scores["deteriorating"] = 0.5
        # |flow| small → neutral falls through

    # squeeze-prone: 売り長 or heavy days-to-cover, esp. when price starts up
    if direct and (uri_naga or (days_to_cover is not None and days_to_cover >= 3)):
        s = 0.45
        if up and vol_up:
            s += 0.2
        if ms_chg is not None and ms_chg > 5:
            s += 0.1                                 # selling balance still building
        scores["squeeze_prone"] = min(1.0, s)

    # credit overhang: buying balance heavy vs volume, or building while price stalls
    if direct and ((buy_overhang_days is not None and buy_overhang_days >= 5)
                   or (mb_chg is not None and mb_chg >= 10 and not up)):
        s = 0.5 + (0.15 if (buy_overhang_days or 0) >= 10 else 0.0)
        scores["credit_overhang"] = min(1.0, s)

    # v11.14.0: 重い水準の改善は「改善中だがまだ重い」— good系には入れない。
    if (has_margin or has_jsf) and level in ("heavy", "very_heavy") \
            and improving_dir and "squeeze_prone" not in scores:
        scores["improving_but_heavy"] = 0.55

    # good: buying overhang light, selling pressure easing, price healthy
    # (JP structure data only — US absence of margin data is NOT lightness).
    # v11.14.0: LEVELが軽い/普通の時だけ — 前週比の改善だけでは入れない。
    if (has_margin or has_jsf) and not uri_naga and level in ("light", "normal"):
        s = 0.35
        if mb_chg is not None and mb_chg < 0:
            s += 0.15                                # 信用買い残が減っている=軽くなる
        if up and vol_up and not ev.get("gapFade"):
            s += 0.15
        if ev.get("instStance") == "bullish" or flow_class == "institutional_accumulation":
            s += 0.1
        if s >= 0.45:
            scores["good"] = min(1.0, s)
        else:
            scores["slightly_good"] = s

    # distribution risk: gap-fade / weak close on volume, or flow says so
    if (ev.get("gapFade") or flow_class in ("distribution", "profit_taking")
            or (_f(ev.get("closeLocation")) is not None and _f(ev.get("closeLocation")) <= 0.3
                and vol_up and up)):
        scores["distribution_risk"] = 0.5

    # deteriorating / bad: price down while credit buying builds (催促相場)
    if down and mb_chg is not None and mb_chg > 0:
        scores["deteriorating"] = 0.5
        if chg <= -3 and mb_chg >= 10:
            scores["bad"] = 0.6
    if down and ev.get("regimeRiskOff") and direct and not uri_naga:
        scores["deteriorating"] = max(scores.get("deteriorating", 0.0), 0.45)

    if not scores:
        condition, base = ("neutral", 0.4) if direct else ("unknown", 0.2)
    else:
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        condition, base = ranked[0]
        if len(ranked) >= 2 and ranked[0][1] - ranked[1][1] < 0.08:
            good_side = {"good", "slightly_good", "very_good", "squeeze_prone"}
            if (ranked[0][0] in good_side) != (ranked[1][0] in good_side):
                condition, base = "mixed", ranked[0][1] - 0.05

    # very_good (→S) is rare and DIRECT-only: light overhang + easing sell
    # pressure + healthy rise + supportive flow, with both feeds present.
    if (condition == "good" and has_margin and has_jsf and up and vol_up
            and mb_chg is not None and mb_chg < 0
            and flow_class == "institutional_accumulation"):
        condition, base = "very_good", max(base, 0.75)

    # ── rank / direction / confidence ───────────────────────────────────────
    rank = {"very_good": "S", "good": "A", "slightly_good": "B",
            "squeeze_prone": "B", "improving_but_heavy": "C",
            "neutral": "C", "mixed": "C",
            "liquidity_thin": "C", "distribution_risk": "D",
            "credit_overhang": "D", "deteriorating": "D", "bad": "E",
            "unknown": "Unknown"}[condition]
    if rank == "S" and not (has_margin and has_jsf):
        rank = "A"                                    # S never on partial data
    # v11.14.0 HARD CAP: 重い買い残は改善中でもA/Sを許さない。
    rank_cap_reason = None
    _rank_order = ["S", "A", "B", "C", "D", "E", "Unknown"]
    if level == "heavy" and _rank_order.index(rank) < _rank_order.index("B"):
        rank, rank_cap_reason = "B", "信用買い残が重い水準のためA/S不可(改善方向でも上限B)"
    elif level == "very_heavy" and _rank_order.index(rank) < _rank_order.index("C"):
        rank, rank_cap_reason = "C", "信用買い残がかなり重い水準のため上限C"
    if rank in ("S", "A") and level not in ("light", "normal"):
        rank, rank_cap_reason = "B", rank_cap_reason or "買い残水準が確認できないためA/S保留"

    if mb_chg is None and ms_chg is None:
        direction = "unknown"
    elif condition == "improving_but_heavy":
        direction = "improving"
    elif condition in ("squeeze_prone",):
        direction = "mixed"
    elif (mb_chg is not None and mb_chg < 0) or (ms_chg is not None and ms_chg < 0 and up):
        direction = "improving"
    elif mb_chg is not None and mb_chg > 10 and not up:
        direction = "worsening"
    else:
        direction = "stable"

    directness = ("direct_data" if direct else
                  "inferred" if chg is not None else "insufficient")
    conf = base
    if directness != "direct_data":
        conf = min(conf, 0.4)
    if direct and not is_us and (not has_margin or not has_jsf):
        conf = min(conf, 0.6)                         # one feed only
    if has_us_flow:
        conf = min(conf, 0.6)                         # US simplified read caps here
    if ev.get("staleData"):
        conf = min(conf, 0.4)
        missing.append("データ鮮度")
    conf = round(max(0.1, conf), 2)

    action = {"very_good": "monitor", "good": "monitor",
              "slightly_good": "add_only_on_pullback",
              "improving_but_heavy": "add_only_on_pullback",
              "squeeze_prone": "avoid_chase", "credit_overhang": "avoid_chase",
              "distribution_risk": "caution", "deteriorating": "wait", "bad": "wait",
              "neutral": "no_action", "mixed": "investigate",
              "liquidity_thin": "no_action", "unknown": "no_action"}[condition]

    why = _why_ja(condition, rank, ratio, days_to_cover, buy_overhang_days,
                  mb_chg, direct, conf, is_us=is_us, measured_flow=measured_flow)
    ev_score = round(sum(1 for v in evidence.values() if v is not None) / len(EVIDENCE_KEYS), 2)
    risk = round(min(1.0, (0.6 if condition in ("credit_overhang", "distribution_risk",
                                                "bad", "deteriorating") else 0.3)
                     + (0.2 if not direct else 0.0)), 2)

    directness_ja = ("実データ(実測フロー)あり" if has_us_flow and directness == "direct_data"
                     else DIRECTNESS_JA[directness])
    return {
        "schemaVersion": SCHEMA_VERSION,
        "id": "sd-" + hashlib.md5(f"{market}:{symbol}:{now_iso[:13]}".encode()).hexdigest()[:10],
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "asOf": now_iso,
        "dataDate": ev.get("marginDate") or ev.get("jsfDate"),
        "sourceUpdatedAt": ev.get("sourceUpdatedAt"),
        "sourceAvailability": {"jqMarginWeekly": has_margin, "jsfDailyBalance": has_jsf,
                               "shortSellingRatio": _f(ev.get("shortSellingRatio")) is not None,
                               "reverseStockLendingFee": False},
        "supplyDemandRank": rank, "rankJa": RANK_JA[rank],
        "supplyDemandLevel": level, "levelJa": LEVEL_JA[level],
        "rankCapReason": rank_cap_reason,
        "condition": condition, "conditionJa": CONDITION_JA[condition],
        "chips": list(CONDITION_CHIPS.get(condition, [])),
        "direction": direction,
        "confidence": conf, "evidenceScore": ev_score, "riskScore": risk,
        "readabilityLabelJa": f"需給ランク {rank}：{CONDITION_JA[condition]}",
        "ownerReadableWhyJa": why,
        "checkNextJa": _check_next_ja(condition),
        "actionImplication": action, "actionImplicationJa": ACTION_JA[action],
        "directness": directness, "directnessJa": directness_ja,
        "evidence": evidence,
        "missingEvidence": missing[:6],
        "sourceLimitNote": (
            "米国は信用残・貸借残に相当する公開日次データが無いため、実測大口フロー+"
            "出来高ベースの簡易判定。空売り残(FINRA・隔週)は未取込。" if is_us and has_us_flow else
            "米国の需給データ(実測フロー/空売り残)が未取得のため、需給ランクは暫定です。"
            if is_us else
            "信用残は週次・貸借残は日次の公表データで、リアルタイムではない。"
            "逆日歩は未取込。" if direct else
            "日証金/信用/空売りデータ未取得のため、需給ランクは暫定です。"),
        "complianceNote": "需給の状態評価であり売買指示ではない。データが無い項目は推定しない。",
        # feed-forward hints for Flow Attribution (v11.10.0 integration)
        "flowHints": {"squeezeProne": condition == "squeeze_prone",
                      "creditOverhang": condition in ("credit_overhang", "improving_but_heavy")
                                        or level in ("heavy", "very_heavy"),
                      "supportsAccumulation": condition in ("very_good", "good")
                                              and level in ("light", "normal")},
    }


def _why_ja(condition, rank, ratio, days_to_cover, buy_overhang_days, mb_chg,
            direct, conf, is_us=False, measured_flow=None):
    if is_us and measured_flow is not None:
        us = {
            'good': f'実測の大口資金が流入超(純比率{measured_flow:+.2f})で、上値を抑える売り圧力は目立たない状態',
            'slightly_good': f'実測の大口資金は流入超(純比率{measured_flow:+.2f})だが、価格の裏付けは限定的',
            'distribution_risk': f'価格が保たれる裏で実測の大口資金が流出超(純比率{measured_flow:+.2f}) — 上値で売られている可能性',
            'deteriorating': f'下落と同時に実測の大口資金も流出超(純比率{measured_flow:+.2f})で、需給は悪化中',
        }
        if condition in us:
            return (us[condition] + '。米国は信用残に相当する公開データが無いため簡易判定。')[:220]

    ratio_txt = (f"貸借倍率{ratio}" if ratio is not None else "")
    base = {
        "very_good": "信用買い残が軽く売り圧力も減少中で、上値を抑える玉が少ない状態",
        "good": "信用買い残の重さは目立たず、上値を抑える玉が比較的少ない状態",
        "slightly_good": "需給はやや良好。ただし決め手となる直接データは限定的",
        "squeeze_prone": (f"売り残が多く({ratio_txt}"
                          + (f"・買い戻し{days_to_cover}日分" if days_to_cover is not None else "")
                          + ")、踏み上げ余地はあります。ただし上昇は買い戻し主導の可能性があり、"
                            "新規の大口買いとは未確定です"),
        "improving_but_heavy": ("信用買い残は前週比で減少しており、需給は改善方向です。"
                                "ただし買い残の絶対量はまだ大きく、上昇時には戻り売りが"
                                "出やすい状態です。A判定には買い残のさらなる減少と"
                                "出来高を伴う上値吸収が必要"),
        "credit_overhang": (f"信用買い残が重く"
                            + (f"(平均出来高の約{buy_overhang_days:.0f}日分)" if buy_overhang_days is not None else "")
                            + "、上がるたびに戻り売りが出やすい状態"),
        "distribution_risk": "上値で売りが出ている可能性(高出来高なのに引けが弱い形)",
        "deteriorating": "需給が悪化しており、買い増しより確認待ちが安全"
                         + (f"(下落中に信用買い残+{mb_chg}%)" if mb_chg is not None and mb_chg > 0 else ""),
        "bad": "下落しながら信用買い残が積み上がる形(いわゆる催促相場)で、需給は悪い",
        "neutral": "需給に明確な偏りは見られません",
        "mixed": "良い材料と重い材料が混在しており、需給の決め打ちは危険",
        "liquidity_thin": "商いが薄く、需給判断に大きな意味を持たせない",
        "unknown": "需給判断に必要なデータが不足しています(日証金/信用/空売りデータ未取得)",
    }[condition]
    tail = "。" if direct else "。データ不足のため暫定です。"
    return (base + tail)[:220]


def _check_next_ja(condition):
    return {
        "very_good": "上昇の継続性(出来高を伴うか)と週次信用残の次回更新を確認",
        "good": "週次信用残の次回更新で買い残が積み上がらないかを確認",
        "slightly_good": "日証金の貸借残と出来高の質を確認",
        "squeeze_prone": "買い戻し一巡後に失速しないか(上昇の主体が入れ替わるか)を確認",
        "credit_overhang": "戻り局面で売りが出るか、信用買い残が減り始めるかを確認",
        "improving_but_heavy": "信用買い残が続けて減るか。上昇日に出来高を伴って高値圏で引けられるか。戻り局面で売りに押されないか",
        "distribution_risk": "翌日以降も高出来高で引けが弱い形が続くかを確認",
        "deteriorating": "信用買い残の増加が止まるか、公式材料が出るかを確認",
        "bad": "投げ売り(残の急減)が出て需給がリセットされるかを確認",
        "neutral": "週次信用残・日証金の次回更新を待つ",
        "mixed": "どちらの材料が優勢になるか、出来高を伴う方向を確認",
        "liquidity_thin": "商いが戻るまで判断を保留",
        "unknown": "データ取得後に再判定(平日にJ-Quants/日証金が更新されます)",
    }[condition]


# ── aggregation for status / handoff / snapshot ─────────────────────────────

def status_doc(signals: List[Dict[str, Any]], *, now_iso: str,
               sources: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schemaVersion": "supply-demand-status-v1", "asOf": now_iso,
        "lastRunAt": now_iso,
        "assetsScanned": len(signals),
        "signalsGenerated": sum(1 for s in signals if s["supplyDemandRank"] != "Unknown"),
        "directDataCount": sum(1 for s in signals if s["directness"] == "direct_data"),
        "inferredOnlyCount": sum(1 for s in signals if s["directness"] == "inferred"),
        "unknownCount": sum(1 for s in signals if s["supplyDemandRank"] == "Unknown"),
        "staleDataCount": sum(1 for s in signals
                              if any("鮮度" in m for m in s["missingEvidence"])),
        "rankDistribution": {r: sum(1 for s in signals if s["supplyDemandRank"] == r)
                             for r in RANKS},
        "latestDataDate": max((s.get("dataDate") or "" for s in signals), default=None) or None,
        "sourcesEnabled": sources.get("enabled", []),
        "sourcesDisabledWithReason": sources.get("disabled", []),
        "directionLevelModelEnabled": True,        # v11.14.0: 方向≠水準
        "heavyOverhangCapEnabled": True,           # heavy→maxB / very_heavy→maxC
        "jsfAvailability": sources.get("jsf", False),
        "marginDataAvailability": sources.get("jqMargin", False),
        "shortSellingDataAvailability": sources.get("shortRatio", False),
        "noteJa": "需給データは公表ベース(週次信用残・日次貸借残)でリアルタイムではない。"
                  "JPのmoomooリアルタイム無効は意図的で、需給判定の欠陥ではない。",
    }


def handoff_section(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    def rows(pred):
        return [f"{s['symbol']} ランク{s['supplyDemandRank']} — {s['ownerReadableWhyJa'][:70]}"
                for s in signals if pred(s)][:4]
    return {
        "title": "Supply / Demand Summary (JP)",
        "best": rows(lambda s: s["supplyDemandRank"] in ("S", "A")),
        "watchPositive": rows(lambda s: s["supplyDemandRank"] == "B"
                              and s["condition"] != "squeeze_prone"),
        "squeezeProne": rows(lambda s: s["condition"] == "squeeze_prone"),
        "creditOverhang": rows(lambda s: s["condition"] == "credit_overhang"),
        "worst": rows(lambda s: s["supplyDemandRank"] in ("D", "E")
                      and s["condition"] != "credit_overhang"),
        "missingEvidence": sorted({m for s in signals for m in s["missingEvidence"]})[:6],
        "directCount": sum(1 for s in signals if s["directness"] == "direct_data"),
        "inferredCount": sum(1 for s in signals if s["directness"] != "direct_data"),
        "sourceLimitJa": "信用残=週次公表・貸借残=日次公表・逆日歩=未取込。"
                         "踏み上げ型の上昇は新規大口買いと断定しない。",
        "disclaimerJa": "需給の状態評価であり売買指示ではない。",
    }


def snapshot_summary(signals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compact block for PortfolioSnapshot / DecisionAuditRecord — future review
    can check whether A/B ranks preceded sustained moves etc."""
    return {
        "supplyDemandSummary": [{"symbol": s["symbol"], "rank": s["supplyDemandRank"],
                                 "condition": s["condition"], "confidence": s["confidence"]}
                                for s in signals[:10]],
        "bestSupplyDemand": [s["symbol"] for s in signals
                             if s["supplyDemandRank"] in ("S", "A")][:5],
        "worstSupplyDemand": [s["symbol"] for s in signals
                              if s["supplyDemandRank"] in ("D", "E")][:5],
        "squeezeProne": [s["symbol"] for s in signals if s["condition"] == "squeeze_prone"][:5],
        "creditOverhang": [s["symbol"] for s in signals if s["condition"] == "credit_overhang"][:5],
        "missingSupplyDemandEvidence": sorted({m for s in signals
                                               for m in s["missingEvidence"]})[:5],
    }
