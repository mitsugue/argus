"""ARGUS V11.11.0 — Decision Quality / Backtest Foundation (pure, deterministic).

ARGUSが過去に出したラベル(avoid_chase / 押し目限定 / 需給A / 買い戻し候補 …)が
その後どうなったかを、後から検証できる形で残す土台。

WHAT THIS IS NOT (hard rules):
  - Not a trading backtester: it measures what happened AFTER ARGUS labels,
    never what the owner traded. Owner actions are optional annotations only.
  - Never fabricates prices/outcomes: missing history → insufficient_price_data.
  - Never presents early results as proven performance — every summary carries
    a notEnoughHistoryNote until labels have real sample sizes (n>=5).
  - Records are immutable at the evidence level: evidenceAtDecision is written
    once; only outcome/ownerAction/review fields may be updated later.
  - PRIVACY: detailed records live device-local (+ encrypted vault). The server
    stores none of them; public status is aggregate-only and redacted.

Interpretation vocabulary (cautious, Japanese):
  supported     「この判断は今のところ支持されています」
  contradicted  「この判断は外れた可能性があります」
  mixed         「一長一短/材料変化があり単純比較はできません」
  inconclusive  「データ不足で判定保留です」
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "decision-quality-v1"
OUTCOME_SCHEMA_VERSION = "decision-outcome-v1"

DECISION_CONTEXTS = ("hold", "monitor", "wait", "avoid_chase", "add_only_on_pullback",
                     "add_allowed_small", "caution", "investigate", "no_action",
                     "trim_consideration", "unknown")
DECISION_SOURCES = ("action_alert", "asset_card", "position_exposure", "flow_attribution",
                    "supply_demand", "institutional_intelligence", "market_regime",
                    "pro_handoff", "snapshot", "combined")
OWNER_ACTIONS = ("bought", "sold", "added", "trimmed", "held", "watched", "skipped", "unknown")
REVIEW_STATUSES = ("pending", "enough_data", "reviewed", "inconclusive", "disabled")
OUTCOME_STATUSES = ("pending", "partial", "complete", "insufficient_price_data",
                    "stale", "market_closed", "unknown")
INTERPRETATIONS = ("supported", "contradicted", "mixed", "inconclusive", "not_applicable")

INTERPRETATION_JA = {
    "supported": "この判断は今のところ支持されています",
    "contradicted": "この判断は外れた可能性があります",
    "mixed": "一長一短の結果です(単純比較はできません)",
    "inconclusive": "データ不足で判定保留です",
    "not_applicable": "この種のラベルは成否判定の対象外です",
}

# keys that must never appear in PUBLIC decision-quality payloads
PUBLIC_FORBIDDEN = ("quantity", "averageCost", "costBasis", "marketValue",
                    "unrealizedPnl", "accountType", "ownerActionNote", "ownerAction",
                    "weightPct", "ownerNote", "broker", "positions", "symbol")


def validate_record(rec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    if rec.get("schemaVersion") != SCHEMA_VERSION:
        errs.append(f"schemaVersion must be {SCHEMA_VERSION}")
    for k in ("id", "symbol", "market", "asOf", "createdAt", "appVersion"):
        if not rec.get(k):
            errs.append(f"{k} required")
    if rec.get("decisionContext") not in DECISION_CONTEXTS:
        errs.append("decisionContext invalid")
    if rec.get("decisionSource") not in DECISION_SOURCES:
        errs.append("decisionSource invalid")
    if rec.get("privacyLevel") not in ("private", "redacted", "local_only"):
        errs.append("privacyLevel invalid")
    if rec.get("ownerAction") is not None and rec.get("ownerAction") not in OWNER_ACTIONS:
        errs.append("ownerAction invalid")
    if rec.get("reviewStatus") not in REVIEW_STATUSES:
        errs.append("reviewStatus invalid")
    if not isinstance(rec.get("evidenceAtDecision"), dict):
        errs.append("evidenceAtDecision must be a dict (immutable once written)")
    return (not errs), errs


def validate_outcome(o: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errs: List[str] = []
    if o.get("schemaVersion") != OUTCOME_SCHEMA_VERSION:
        errs.append(f"schemaVersion must be {OUTCOME_SCHEMA_VERSION}")
    for k in ("decisionId", "symbol", "basePrice", "basePriceAt"):
        if o.get(k) in (None, ""):
            errs.append(f"{k} required")
    if o.get("outcomeStatus") not in OUTCOME_STATUSES:
        errs.append("outcomeStatus invalid")
    if o.get("outcomeInterpretation") is not None \
            and o.get("outcomeInterpretation") not in INTERPRETATIONS:
        errs.append("outcomeInterpretation invalid")
    return (not errs), errs


def dedupe_key(symbol: str, decision_context: str, day: str,
               reason_codes: Optional[List[str]] = None) -> str:
    """symbol+context+date(+major reason) — one record per situation per day."""
    major = (sorted(reason_codes)[0] if reason_codes else "")
    return f"{str(symbol).upper()}|{decision_context}|{day}|{major}"


# ── outcome computation (trading-day series → forward returns) ──────────────

def compute_outcome(decision_id: str, symbol: str, market: str,
                    base_price: Optional[float], base_date: str,
                    dates_newest_first: List[str], closes_newest_first: List[float],
                    now_date: str) -> Dict[str, Any]:
    """Forward returns at +1/+3/+5/+20 TRADING days after base_date. The series
    contains only trading days, so weekends/holidays are handled by construction
    (the +1d close is the NEXT available market close). Missing data is
    insufficient_price_data — prices are never invented."""
    out: Dict[str, Any] = {
        "schemaVersion": OUTCOME_SCHEMA_VERSION, "decisionId": decision_id,
        "symbol": str(symbol).upper(), "market": str(market).upper(),
        "basePrice": base_price, "basePriceAt": base_date,
        "outcomePrice1d": None, "outcomeReturn1d": None,
        "outcomePrice3d": None, "outcomeReturn3d": None,
        "outcomePrice5d": None, "outcomeReturn5d": None,
        "outcomePrice20d": None, "outcomeReturn20d": None,
        "maxDrawdown5d": None, "maxRunup5d": None,
        "maxDrawdown20d": None, "maxRunup20d": None,
        "outcomeStatus": "pending", "outcomeInterpretation": None,
        "outcomeReadableJa": None, "updatedAt": now_date,
    }
    if not base_price or base_price <= 0 or not dates_newest_first or not closes_newest_first:
        out["outcomeStatus"] = "insufficient_price_data" if base_price else "unknown"
        return out
    # ascending (oldest→newest) trading-day series strictly AFTER the base date
    series = sorted(zip(dates_newest_first, closes_newest_first), key=lambda x: x[0] or "")
    fwd = [(d, c) for d, c in series if d and d > base_date and isinstance(c, (int, float))]
    if not fwd:
        # base date newer than any close we hold → windows not elapsed yet
        out["outcomeStatus"] = "pending" if base_date >= (series[-1][0] or "") else "insufficient_price_data"
        return out

    def ret(px):
        return round((px - base_price) / base_price * 100, 2)

    windows = {1: ("outcomePrice1d", "outcomeReturn1d"), 3: ("outcomePrice3d", "outcomeReturn3d"),
               5: ("outcomePrice5d", "outcomeReturn5d"), 20: ("outcomePrice20d", "outcomeReturn20d")}
    filled = 0
    for n, (pk, rk) in windows.items():
        if len(fwd) >= n:
            px = float(fwd[n - 1][1])
            out[pk], out[rk] = px, ret(px)
            filled += 1
    for n, (dk, uk) in ((5, ("maxDrawdown5d", "maxRunup5d")),
                        (20, ("maxDrawdown20d", "maxRunup20d"))):
        win = [float(c) for _, c in fwd[:n]]
        if win:
            out[dk] = round((min(win) - base_price) / base_price * 100, 2)
            out[uk] = round((max(win) - base_price) / base_price * 100, 2)
    out["outcomeStatus"] = ("complete" if filled == 4 else
                            "partial" if filled else "pending")
    return out


# ── cautious interpretation rules ───────────────────────────────────────────

def interpret(decision_context: str, evidence: Dict[str, Any],
              outcome: Dict[str, Any]) -> Tuple[str, str]:
    """(interpretation, readableJa). Deterministic and deliberately modest —
    when in doubt it says mixed/inconclusive, never claims proof."""
    r1, r3 = outcome.get("outcomeReturn1d"), outcome.get("outcomeReturn3d")
    r5, r20 = outcome.get("outcomeReturn5d"), outcome.get("outcomeReturn20d")
    dd5, ru5 = outcome.get("maxDrawdown5d"), outcome.get("maxRunup5d")
    if evidence.get("eventChanged"):
        return "mixed", "材料変化があり単純比較はできません。"
    if r3 is None and r5 is None:
        return "inconclusive", INTERPRETATION_JA["inconclusive"]
    r5x = r5 if r5 is not None else r3
    sd_rank = str(evidence.get("supplyDemandRank") or "")
    sd_cond = str(evidence.get("supplyDemandCondition") or "")
    flow = str(evidence.get("flowClass") or "")

    if decision_context == "avoid_chase":
        if (dd5 is not None and dd5 <= -3) or (r5x is not None and r5x <= -1):
            return "supported", ("追いかけ買いを避けた後に押し(下落)が来ており、"
                                 + INTERPRETATION_JA["supported"] + "。")
        if r5x is not None and r5x >= 5 and (dd5 is None or dd5 > -2):
            return "contradicted", ("押し目なくそのまま上昇が続いたため、"
                                    + INTERPRETATION_JA["contradicted"] + "。")
        if dd5 is not None and dd5 <= -3 and r5x is not None and r5x >= 3:
            return "mixed", "一度押した後に回復しており、一長一短の結果です。"
        return "mixed", "大きな押しも急伸もなく、判定は中間です。"

    if decision_context == "add_only_on_pullback":
        if dd5 is not None and dd5 <= -2:
            return "supported", ("実際に押し目が発生しており、"
                                 + INTERPRETATION_JA["supported"] + "。")
        if r5x is not None and r5x >= 5 and (dd5 is None or dd5 > -1.5):
            return "contradicted", ("押し目が来ないまま上昇が続き、機会を逃した可能性があります。")
        return "mixed", "浅い押しにとどまり、一長一短の結果です。"

    if sd_rank in ("S", "A", "B") and decision_context in ("monitor", "hold",
                                                           "add_allowed_small"):
        if sd_cond == "squeeze_prone" or flow == "short_covering":
            if ru5 is not None and ru5 >= 3 and r5x is not None and r5x < ru5 - 2:
                return "supported", ("踏み上げ型どおり急伸後に失速しており、"
                                     "買い戻し主導の読みと整合的です。")
            if r20 is not None and r20 >= 8:
                return "contradicted", ("失速せず上昇が継続しており、買い戻し以外の"
                                        "買いが入っていた可能性があります。")
            return "mixed", "踏み上げと実需買いの両方が混在した可能性があります。"
        if r5x is not None and r5x >= 2:
            return "supported", ("需給良好の読みどおり続伸しており、"
                                 + INTERPRETATION_JA["supported"] + "。")
        if r5x is not None and r5x <= -3:
            return "contradicted", ("需給良好にもかかわらず下落しており、"
                                    + INTERPRETATION_JA["contradicted"] + "。")
        return "mixed", "需給良好の後の値動きは中立で、判定は中間です。"

    if sd_rank in ("D", "E") and decision_context in ("wait", "caution", "avoid_chase",
                                                      "monitor", "trim_consideration"):
        if (r5x is not None and r5x <= -2) or (ru5 is not None and ru5 < 2):
            return "supported", ("需給が重い読みどおり戻りが弱く、"
                                 + INTERPRETATION_JA["supported"] + "。")
        if r5x is not None and r5x >= 5:
            return "contradicted", ("需給の重さを突き抜けて上昇しており、"
                                    + INTERPRETATION_JA["contradicted"] + "。")
        return "mixed", "需給の重さと値動きが拮抗しており、判定は中間です。"

    if decision_context in ("caution", "wait", "investigate", "trim_consideration"):
        if r5x is not None and r5x <= -2:
            return "supported", "警戒どおり弱い値動きとなり、" + INTERPRETATION_JA["supported"] + "。"
        if r5x is not None and r5x >= 5:
            return "contradicted", "警戒に反して強い上昇となりました。"
        return "mixed", "警戒後の値動きは中立で、判定は中間です。"

    if decision_context in ("monitor", "hold", "no_action", "add_allowed_small", "unknown"):
        # institutional-only signals: only judge when the signal was direct
        if evidence.get("institutionalSignals") and not evidence.get("institutionalDirect"):
            return "not_applicable", ("見出しのみの機関シグナルは確度が低いため、"
                                      "成否判定の対象外です。")
        return "not_applicable", INTERPRETATION_JA["not_applicable"]
    return "inconclusive", INTERPRETATION_JA["inconclusive"]


# ── summary / status ────────────────────────────────────────────────────────

_MIN_SAMPLE = 5


def summary(records: List[Dict[str, Any]], now_iso: str) -> Dict[str, Any]:
    """DecisionQualitySummary — label-level tallies. Labels below _MIN_SAMPLE
    are 'not enough history', never ranked best/noisy."""
    def interp(r):
        return ((r.get("outcome") or {}).get("outcomeInterpretation"))
    by_ctx: Dict[str, Dict[str, int]] = {}
    by_mod: Dict[str, int] = {}
    by_mkt: Dict[str, int] = {}
    counts = {"supported": 0, "contradicted": 0, "mixed": 0, "inconclusive": 0}
    pending = enough = 0
    for r in records:
        ctx = r.get("decisionContext") or "unknown"
        by_ctx.setdefault(ctx, {"n": 0, "supported": 0, "contradicted": 0})
        by_ctx[ctx]["n"] += 1
        by_mod[r.get("decisionSource") or "combined"] = by_mod.get(r.get("decisionSource") or "combined", 0) + 1
        by_mkt[r.get("market") or "?"] = by_mkt.get(r.get("market") or "?", 0) + 1
        it = interp(r)
        if it in counts:
            counts[it] += 1
        if it in ("supported",):
            by_ctx[ctx]["supported"] += 1
        if it in ("contradicted",):
            by_ctx[ctx]["contradicted"] += 1
        st = ((r.get("outcome") or {}).get("outcomeStatus"))
        if st in ("complete", "partial"):
            enough += 1
        else:
            pending += 1
    best, noisy = [], []
    for ctx, c in by_ctx.items():
        judged = c["supported"] + c["contradicted"]
        if judged >= _MIN_SAMPLE:
            rate = c["supported"] / judged
            (best if rate >= 0.6 else noisy if rate <= 0.4 else []).append(
                {"label": ctx, "supportRate": round(rate, 2), "n": judged})
    return {
        "schemaVersion": "decision-quality-summary-v1", "asOf": now_iso,
        "recordsTotal": len(records), "pendingCount": pending,
        "enoughDataCount": enough, "reviewedCount":
            sum(1 for r in records if r.get("reviewStatus") == "reviewed"),
        "byDecisionContext": {k: v["n"] for k, v in by_ctx.items()},
        "byModule": by_mod, "byMarket": by_mkt,
        "supportedCount": counts["supported"], "contradictedCount": counts["contradicted"],
        "mixedCount": counts["mixed"], "inconclusiveCount": counts["inconclusive"],
        "bestPerformingLabels": best, "noisyLabels": noisy,
        "notEnoughHistoryNote": ("まだ十分な履歴がないため、成績としては扱わないで"
                                 "ください(ラベルごとにn≥5で初めて傾向を表示)。"
                                 if not best and not noisy else
                                 "サンプルは増加中 — 傾向は参考値であり将来を保証しない。"),
        "privacyLevel": "local_only",
    }


def public_status(*, enabled: bool, storage_mode: str, now_iso: str) -> Dict[str, Any]:
    """The ONLY decision-quality payload a public endpoint may serve. Aggregate
    architecture facts — no symbols, no counts tied to holdings, no actions."""
    doc = {
        "schemaVersion": "decision-quality-status-v1", "asOf": now_iso,
        "featureEnabled": enabled,
        "storageMode": storage_mode,          # local_only | encrypted_vault | disabled
        "recordSchemaVersion": SCHEMA_VERSION,
        "outcomeSchemaVersion": OUTCOME_SCHEMA_VERSION,
        "serverStoresRecords": False,
        "publicLeakSafe": True,
        "noteJa": "判断品質の記録は端末内(+暗号化バックアップ)にのみ保存され、"
                  "サーバーには一切保存されない。この公開ステータスは構成情報のみ。",
        "notEnoughHistoryNote": "履歴が十分に貯まるまで、成績として扱わないでください。",
    }
    return doc
