"""A.R.G.U.S. — Decision Value Ledger v1 (Phase 1: pure engine).

RESEARCH SIMULATION ONLY. No order was or will be submitted. This module contains
NO broker client, NO order routes, NO execute/buy/sell side effects — only the
math to answer: "if a clearly-defined, immutable decision policy had been
followed, did it have positive value AFTER realistic costs and risk?"

This is SEPARATE from the Calibration Ledger (which measures probability quality:
Brier/RPS). A good Brier does not prove a profitable strategy; a high win rate
does not prove positive expectancy; a positive gross return does not prove
positive NET expectancy. This engine keeps gross and net strictly separate.

Pure-stdlib, side-effect-free, deterministic (Monte Carlo takes an explicit seed).
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Sequence

DECISION_VALUE_SCHEMA = "decision-value-v1"
COST_MODEL_VERSION = "cost-model-v1"
RISK_MODEL_VERSION = "risk-model-v1"
POLICY_REGISTRY_VERSION = "policy-registry-v1"
DISCLAIMER = "Research simulation only. No order was or will be submitted."

# ── Policy Registry (section 4/5): immutable, chosen BEFORE outcomes ──────────
# Each policy fully defines eligibility/entry/exit/invalidation so a shadow result
# is reproducible and free of hindsight. Long-only, research-only; NO execution.
POLICIES = {
    "daily_next_session_long_v1": {
        "label": "Daily next-session long (eligible post-close long signals)",
        "direction": "long",
        "entryRule": "next eligible regular-session executable price (ask/conservative); "
                     "NEVER the prior close as if executable after the decision",
        "exits": ["1D close", "3D close", "5D close"],
        "invalidationRule": "machine-readable + fixed at decision time, else none",
        "noFill": ["stale quote", "no executable price", "after deadline", "unsupported entitlement"],
    },
    "close_pin_long_v1": {
        "label": "Close-pin long (eligible close-pin candidates only)",
        "direction": "long",
        "entryRule": "first executable price after the decision ts and before the freeze; "
                     "actual bid/ask when available else conservative est (marked estimated)",
        "exits": ["same-day closing auction"],
        "noFill": ["no eligible quote", "stale", "spread too wide", "limit state", "after deadline"],
    },
    "event_next_open_long_v1": {
        "label": "Event next-open long (after-hours official/research events)",
        "direction": "long",
        "entryRule": "next regular-session first executable price; account for opening gap; "
                     "NEVER PTS unless a licensed PTS source exists",
        "exits": ["1D close", "3D close", "5D close"],
        "noFill": ["asset does not trade", "stale", "after deadline"],
    },
    "no_trade_control_v1": {
        "label": "No-trade control (WAIT / NO_ACTION / AVOID_CHASING / rejected)",
        "direction": "none",
        "entryRule": "no trade is invented",
        "tracks": ["future MFE", "future MAE", "avoidedDrawdown", "missedUpside", "gap risk"],
        "note": "descriptive only; never combined with trade P&L as the same utility",
    },
}

# Comparison baselines (section 11) — same dates/horizons/costs as the policy.
BASELINE_POLICIES = {
    "no_trade": "never enter",
    "unconditional_next_open_long": "always go long next open (matched universe)",
    "buy_and_hold": "hold the asset over the same horizon",
    "previous_day_momentum": "long if prior return > band, else flat",
    "market_regime_only": "act only on the pre-forecast regime classification",
    "random_matched": "random candidate selection with matched count/liquidity",
}


def list_policies():
    return {"policyRegistryVersion": POLICY_REGISTRY_VERSION,
            "policies": POLICIES, "baselines": BASELINE_POLICIES,
            "disclaimer": DISCLAIMER + " No broker, no order routes."}


def get_policy(policy_id):
    return POLICIES.get(policy_id)


def validate_policy_timing(*, decision_ts, entry_ts, outcome_ts):
    """No-hindsight guard: entry must be AFTER the decision and BEFORE the outcome
    is known. Rejects same-/prior-close entries after a post-close decision."""
    if decision_ts is None or entry_ts is None:
        return {"ok": False, "reason": "missing_timestamps"}
    if entry_ts < decision_ts:
        return {"ok": False, "reason": "entry_before_decision (hindsight)"}
    if outcome_ts is not None and outcome_ts <= entry_ts:
        return {"ok": False, "reason": "outcome_at_or_before_entry (hindsight)"}
    return {"ok": True, "reason": None}


def build_shadow_decision(*, policy_id, symbol, market, decision_price,
                          decision_ts, entry_ts=None, eligible=True,
                          rejection_reason=None, posture_before=None, posture_after=None,
                          confidence_before=None, confidence_after=None,
                          blocked_actions=None, visibility_downgraded=False,
                          official_event=None):
    """Construct an IMMUTABLE shadow-decision skeleton at decision time (outcome
    filled later). Pins the policy version + identity; never invents an entry from
    the best price. Now also captures the VISIBILITY/posture context at decision time
    (v11) so a decision that was capped/blocked by the guard is auditable later.
    SHADOW/RESEARCH ONLY — no order is created."""
    policy = POLICIES.get(policy_id)
    if not policy:
        return {"ok": False, "reason": "unknown_policy"}
    return {
        "schemaVersion": DECISION_VALUE_SCHEMA,
        "policyId": policy_id, "policyRegistryVersion": POLICY_REGISTRY_VERSION,
        "symbol": symbol, "market": market, "direction": policy["direction"],
        "decisionPrice": decision_price, "decisionTs": decision_ts,
        "plannedEntryRule": policy["entryRule"], "plannedExits": policy.get("exits"),
        "eligibilityResult": "eligible" if eligible else "rejected",
        "rejectionReason": rejection_reason,
        # Visibility / posture context at decision time (audit; v11).
        "postureBefore": posture_before, "postureAfter": posture_after,
        "confidenceBefore": confidence_before, "confidenceAfter": confidence_after,
        "blockedActions": list(blocked_actions or []),
        "visibilityDowngraded": bool(visibility_downgraded),
        # Official-event context at decision time (v11.3) — what the desk KNEW about the
        # disclosure lifecycle when it decided. None when no official event was linked.
        "officialEventId": (official_event or {}).get("officialEventId"),
        "lifecycleStageAtDecision": (official_event or {}).get("lifecycleStage"),
        "causeStatusAtDecision": (official_event or {}).get("causeStatus"),
        "marketReactionKnownAtDecision": bool((official_event or {}).get("marketConfirmed")),
        "missingConfirmationsAtDecision": list((official_event or {}).get("missingConfirmations") or [])[:6],
        "fillStatus": "pending", "outcomeStatus": "pending",
        "realizedOutcomeStatus": "pending",
        "kind": "shadow_candidate" if eligible else "shadow_no_trade",
        "disclaimer": DISCLAIMER,
    }

# ── Cost model (section 6): versioned, with quality status ───────────────────
# Conservative liquidity-bucket spread proxies (bps) when real bid/ask is absent.
_SPREAD_PROXY_BPS = {"high": 3.0, "mid": 8.0, "low": 25.0, "unknown": 15.0}
_COMMISSION_BPS = {"JP": 0.0, "US": 0.0, "CRYPTO": 10.0}  # owner may override JP/US


def estimate_costs(
    *,
    notional: float,
    market: str,
    liquidity_bucket: str = "unknown",
    spread_bps_observed: Optional[float] = None,
    slippage_bps: Optional[float] = None,
    commission_bps: Optional[float] = None,
    fx_bps: float = 0.0,
    borrow_bps: float = 0.0,
) -> Dict[str, Any]:
    """Estimate round-trip-ish execution costs in bps + absolute. Marks each
    component observed vs estimated vs conservative_fallback. Never fabricates a
    real spread — uses a liquidity-bucket proxy and SAYS so."""
    if spread_bps_observed is not None:
        spread, spread_q = float(spread_bps_observed), "observed"
    else:
        spread = _SPREAD_PROXY_BPS.get(liquidity_bucket, _SPREAD_PROXY_BPS["unknown"])
        spread_q = "conservative_fallback"
    # slippage default: half the spread (estimated) unless given
    if slippage_bps is not None:
        slip, slip_q = float(slippage_bps), "estimated"
    else:
        slip, slip_q = spread / 2.0, "estimated"
    comm = commission_bps if commission_bps is not None else _COMMISSION_BPS.get((market or "").upper(), 0.0)
    total_bps = spread + slip + comm + fx_bps + borrow_bps
    return {
        "costModelVersion": COST_MODEL_VERSION,
        "spreadBps": round(spread, 4), "spreadQuality": spread_q,
        "slippageBps": round(slip, 4), "slippageQuality": slip_q,
        "commissionBps": round(comm, 4), "fxBps": round(fx_bps, 4),
        "borrowBps": round(borrow_bps, 4),
        "totalCostBps": round(total_bps, 4),
        "totalCostAbs": round(notional * total_bps / 1e4, 6),
    }


# ── Outcome math (section 3/6/7): gross vs net kept separate ──────────────────
def gross_return_pct(entry: float, exit_: float, direction: str = "long") -> Optional[float]:
    if not entry or entry <= 0 or exit_ is None:
        return None
    raw = (exit_ - entry) / entry * 100.0
    return raw if direction == "long" else -raw


def net_return_pct(gross_pct: Optional[float], total_cost_bps: float) -> Optional[float]:
    if gross_pct is None:
        return None
    return round(gross_pct - total_cost_bps / 100.0, 6)  # bps→pct


def r_multiple(
    *, entry: float, exit_: float, invalidation: float, direction: str = "long",
    total_cost_bps: float = 0.0,
) -> Dict[str, Any]:
    """Normalized R. 1R = planned max loss = |entry - invalidation| per unit. If no
    valid risk distance exists, R is null (do NOT invent a stop after the fact)."""
    if not entry or entry <= 0 or invalidation is None:
        return {"grossR": None, "netR": None, "plannedRiskPerUnit": None,
                "reason": "no_entry_or_invalidation"}
    risk = abs(entry - invalidation)
    if risk <= 0:
        return {"grossR": None, "netR": None, "plannedRiskPerUnit": 0.0,
                "reason": "zero_risk_distance"}
    move = (exit_ - entry) if direction == "long" else (entry - exit_)
    cost_per_unit = entry * (total_cost_bps / 1e4)
    return {
        "plannedRiskPerUnit": round(risk, 6),
        "grossR": round(move / risk, 4),
        "netR": round((move - cost_per_unit) / risk, 4),
        "reason": None,
    }


# ── Expectancy (section 9): only from completed, comparable records ───────────
def expectancy(net_rs: Sequence[float], *, flat_tol: float = 0.05) -> Dict[str, Any]:
    """Net-expectancy metrics from completed netR records. Wins netR>tol, losses
    netR<-tol, else flat. Reports both expectancy and a small-sample warning."""
    rs = [float(r) for r in net_rs if r is not None]
    n = len(rs)
    if n == 0:
        return {"n": 0, "status": "insufficient_sample"}
    wins = [r for r in rs if r > flat_tol]
    losses = [r for r in rs if r < -flat_tol]
    flats = [r for r in rs if -flat_tol <= r <= flat_tol]
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss_mag = abs(sum(losses) / len(losses)) if losses else 0.0
    win_rate = len(wins) / n
    loss_rate = len(losses) / n
    net_exp = sum(rs) / n
    gross_wins = sum(wins)
    gross_losses = abs(sum(losses))
    profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None
    rs_sorted = sorted(rs)
    median = rs_sorted[n // 2] if n % 2 else (rs_sorted[n // 2 - 1] + rs_sorted[n // 2]) / 2
    return {
        "n": n, "winRate": round(win_rate, 4), "lossRate": round(loss_rate, 4),
        "flatRate": round(len(flats) / n, 4),
        "averageWinR": round(avg_win, 4), "averageLossR": round(avg_loss_mag, 4),
        "payoffRatio": round(avg_win / avg_loss_mag, 4) if avg_loss_mag > 0 else None,
        "netExpectancyR": round(net_exp, 4), "medianNetR": round(median, 4),
        "profitFactor": round(profit_factor, 4) if profit_factor is not None else None,
        "sampleStage": _sample_stage(n),
        "warning": "insufficient_sample" if n < 30 else None,
        "disclaimer": DISCLAIMER,
    }


def _sample_stage(n: int) -> str:
    if n < 30:
        return "burn_in"
    if n < 60:
        return "exploratory"
    if n < 120:
        return "provisional"
    return "validation"   # never "proven"


# ── No-trade decision value (section 15): kept SEPARATE from P&L ──────────────
def no_trade_value(observations: Sequence[Dict[str, float]],
                   *, severe_mae: float = 5.0, large_mfe: float = 5.0) -> Dict[str, Any]:
    """Evaluate WAIT/NO_ACTION/AVOID decisions. Each obs: {mae_pct, mfe_pct}
    (the path AFTER the rejection). avoidedDrawdown = caution was right; missed
    upside = opportunity cost (NOT a monetary loss)."""
    obs = [o for o in observations if isinstance(o, dict)]
    n = len(obs)
    if n == 0:
        return {"n": 0, "status": "insufficient_sample"}
    severe_avoided = sum(1 for o in obs if abs(o.get("mae_pct", 0)) >= severe_mae)
    large_missed = sum(1 for o in obs if o.get("mfe_pct", 0) >= large_mfe)
    maes = sorted(abs(o.get("mae_pct", 0)) for o in obs)
    mfes = sorted(o.get("mfe_pct", 0) for o in obs)
    return {
        "n": n,
        "severeLossAvoidanceRate": round(severe_avoided / n, 4),
        "missedLargeGainRate": round(large_missed / n, 4),
        "medianAvoidedMAE": round(maes[n // 2], 4),
        "medianMissedMFE": round(mfes[n // 2], 4),
        "note": "missed upside is OPPORTUNITY COST, not a realized monetary loss; "
                "kept separate from trade expectancy.",
        "disclaimer": DISCLAIMER,
    }


# ── Risk of ruin / drawdown (section 13): block-bootstrap Monte Carlo ─────────
def risk_of_ruin(
    net_rs: Sequence[float],
    *,
    risk_fraction: float = 0.01,
    trials: int = 2000,
    horizon: int = 250,
    block: int = 5,
    drawdown_thresholds: Sequence[float] = (0.20, 0.30, 0.50),
    seed: int = 12345,
) -> Dict[str, Any]:
    """Block-bootstrap Monte Carlo on the empirical netR distribution (preserves
    loss clustering). Each step risks `risk_fraction` of equity × the sampled R.
    Returns P(max drawdown ≥ threshold), equity percentiles, loss-streak. Research
    only; historical tails may understate future tails."""
    rs = [float(r) for r in net_rs if r is not None]
    if len(rs) < 10:
        return {"status": "insufficient_sample", "n": len(rs),
                "note": "need ≥10 completed records for a meaningful simulation"}
    rng = random.Random(seed)
    exceed = {t: 0 for t in drawdown_thresholds}
    endings, max_dds, streaks = [], [], []
    for _ in range(trials):
        equity, peak, max_dd, cur_streak, worst_streak = 1.0, 1.0, 0.0, 0, 0
        i = 0
        while i < horizon:
            start = rng.randrange(len(rs))
            for k in range(block):
                if i >= horizon:
                    break
                r = rs[(start + k) % len(rs)]
                equity *= (1.0 + risk_fraction * r)
                if equity <= 0:
                    equity = 1e-9
                peak = max(peak, equity)
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)
                if r < 0:
                    cur_streak += 1
                    worst_streak = max(worst_streak, cur_streak)
                else:
                    cur_streak = 0
                i += 1
        for t in drawdown_thresholds:
            if max_dd >= t:
                exceed[t] += 1
        endings.append(equity)
        max_dds.append(max_dd)
        streaks.append(worst_streak)
    endings.sort(); max_dds.sort()

    def pct(arr, p):
        return arr[min(len(arr) - 1, int(p * len(arr)))]
    return {
        "riskModelVersion": RISK_MODEL_VERSION, "status": "ok",
        "riskFraction": risk_fraction, "trials": trials, "horizon": horizon,
        "probExceedDrawdown": {f"{int(t*100)}%": round(exceed[t] / trials, 4)
                               for t in drawdown_thresholds},
        "medianMaxDrawdown": round(pct(max_dds, 0.5), 4),
        "p95MaxDrawdown": round(pct(max_dds, 0.95), 4),
        "medianEndingEquity": round(pct(endings, 0.5), 4),
        "p5EndingEquity": round(pct(endings, 0.05), 4),
        "longestLossStreakMax": max(streaks),
        "caveats": ["sample-size dependent", "historical tails may understate future tails",
                    "regime changes can invalidate the distribution"],
        "disclaimer": DISCLAIMER,
    }


def loss_recovery_pct(drawdown_frac: float) -> float:
    """Gain needed to recover a drawdown: 1/(1-dd) - 1. e.g. 0.5 → 1.0 (100%)."""
    if drawdown_frac >= 1.0:
        return float("inf")
    return round(1.0 / (1.0 - drawdown_frac) - 1.0, 4)


# ── Kelly (section 14): DISABLED by default as actionable advice ──────────────
def kelly_research(
    expectancy_metrics: Dict[str, Any],
    *,
    min_sample: int = 60,
    lower_conf_bound_positive: bool = False,
    cap_fraction: float = 0.25,
) -> Dict[str, Any]:
    """Research-only Kelly. Refuses unless positive net expectancy AND sufficient
    sample AND a positive lower confidence bound. Never says "use full Kelly"."""
    n = expectancy_metrics.get("n", 0)
    net_exp = expectancy_metrics.get("netExpectancyR")
    payoff = expectancy_metrics.get("payoffRatio")
    win = expectancy_metrics.get("winRate")
    if n < min_sample:
        return {"kellyStatus": "disabled_insufficient_sample", "n": n, "actionable": False}
    if net_exp is None or net_exp <= 0:
        return {"kellyStatus": "negative_edge", "actionable": False}
    if not lower_conf_bound_positive:
        return {"kellyStatus": "unstable_lower_bound_not_positive", "actionable": False}
    if not payoff or payoff <= 0 or win is None:
        return {"kellyStatus": "indeterminate", "actionable": False}
    full = win - (1 - win) / payoff          # Kelly fraction (b=payoff)
    full = max(0.0, full)
    capped = min(full, cap_fraction)
    return {
        "kellyStatus": "research_only", "actionable": False,
        "fullKellyEstimate": round(full, 4), "halfKelly": round(full / 2, 4),
        "quarterKelly": round(full / 4, 4), "cappedResearchFraction": round(capped, 4),
        "note": "Research only. Never use full Kelly. Estimation error is large.",
        "disclaimer": DISCLAIMER,
    }


# ── Shadow scoring + per-policy aggregation (Phase 1 START, v10.195) ──────────
# Score an immutable shadow candidate AFTER the outcome window, and aggregate by
# policy. RESEARCH SIMULATION ONLY — no order was or will be submitted. Real entry/
# exit prices live only in the owner-private store; this math never fabricates fills.

def score_shadow_record(*, record, entry_price, entry_ts, exit_price,
                        invalidation=None, liquidity_bucket="unknown",
                        cost_overrides=None):
    """Fill + score one shadow_candidate. Enforces the no-hindsight timing guard
    first; a no-trade control record is scored on avoided-loss/missed-upside only
    (never P&L). Returns the SAME record dict, mutated with outcome fields."""
    rec = dict(record or {})
    direction = rec.get("direction") or "long"
    decision_ts = rec.get("decisionTs")

    # No-trade control: no position → measure only what price DID (for no_trade_value).
    if direction == "none" or rec.get("kind") == "shadow_no_trade" or rec.get("policyId") == "no_trade_control_v1":
        dp = rec.get("decisionPrice")
        realized = None
        if dp and exit_price is not None and dp > 0:
            realized = round((exit_price / dp - 1.0) * 100.0, 4)
        rec.update({"fillStatus": "no_trade", "outcomeStatus": "scored",
                    "realizedMovePct": realized, "disclaimer": DISCLAIMER})
        return rec

    timing = validate_policy_timing(decision_ts=decision_ts, entry_ts=entry_ts, outcome_ts=None)
    if not timing["ok"]:
        rec.update({"fillStatus": "rejected_hindsight", "outcomeStatus": "rejected",
                    "rejectionReason": timing["reason"], "disclaimer": DISCLAIMER})
        return rec

    if entry_price is None or exit_price is None or not entry_price:
        rec.update({"fillStatus": "no_fill", "outcomeStatus": "no_fill",
                    "reason": "missing_prices", "disclaimer": DISCLAIMER})
        return rec

    co = cost_overrides or {}
    costs = estimate_costs(notional=entry_price, market=rec.get("market") or "",
                           liquidity_bucket=liquidity_bucket, **co)
    gross = gross_return_pct(entry_price, exit_price, direction)
    net = net_return_pct(gross, costs["totalCostBps"])
    rm = r_multiple(entry=entry_price, exit_=exit_price,
                    invalidation=invalidation if invalidation is not None else entry_price * (0.97 if direction == "long" else 1.03),
                    direction=direction, total_cost_bps=costs["totalCostBps"])
    rec.update({
        "fillStatus": "filled", "outcomeStatus": "scored",
        "entryPrice": entry_price, "entryTs": entry_ts, "exitPrice": exit_price,
        "grossReturnPct": gross, "netReturnPct": net,
        "grossR": rm.get("grossR"), "netR": rm.get("netR"),
        "costBps": costs["totalCostBps"], "costModelVersion": costs["costModelVersion"],
        "disclaimer": DISCLAIMER,
    })
    return rec


def aggregate_by_policy(records):
    """Per-policy expectancy + risk-of-ruin + sample stage from scored records. The
    no-trade control is aggregated SEPARATELY (never mixed with P&L). Never reports
    'proven' — _sample_stage caps the vocabulary."""
    trade_rs = {}          # policyId -> [netR,...]
    no_trade_obs = {}      # policyId -> [{avoidedLoss/missedUpside}...]
    for r in (records or []):
        if not isinstance(r, dict):
            continue
        pid = r.get("policyId")
        if not pid:
            continue
        if r.get("policyId") == "no_trade_control_v1" or r.get("direction") == "none":
            mv = r.get("realizedMovePct")
            if mv is not None:
                no_trade_obs.setdefault(pid, []).append(
                    {"avoidedLoss": max(0.0, -mv), "missedUpside": max(0.0, mv)})
            continue
        if r.get("outcomeStatus") == "scored" and r.get("netR") is not None:
            trade_rs.setdefault(pid, []).append(float(r["netR"]))

    out = {"policyRegistryVersion": POLICY_REGISTRY_VERSION, "policies": {}, "noTrade": {},
           "disclaimer": DISCLAIMER}
    for pid, rs in trade_rs.items():
        exp = expectancy(rs)
        out["policies"][pid] = {
            "n": len(rs), "sampleStage": _sample_stage(len(rs)),
            "expectancy": exp, "riskOfRuin": risk_of_ruin(rs),
        }
    for pid, obs in no_trade_obs.items():
        out["noTrade"][pid] = {"n": len(obs), "sampleStage": _sample_stage(len(obs)),
                               "value": no_trade_value(obs)}
    return out
