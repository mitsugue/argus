"""A.R.G.U.S. — Calibration Ledger v4 foundation (Phase 1).

Pure-stdlib, side-effect-free engine for the calibration overhaul. This module
defines the *vocabulary and math* of Calibration Ledger v4 and nothing else — it
does NOT read/write the live `ledger` git branch, does NOT touch the recording
workflow, and therefore cannot endanger the existing burn-in records (n≈133).
Later phases wire these functions into scanner.py + prediction-ledger.yml.

Design rules honored here:
- proper scoring rules (Brier, RPS) are primary; argmax accuracy is auxiliary
- ordered 3-class scenarios: downside_continuation < sideways_stabilization < rebound_attempt
- no-lookahead volatility bands: band(h) = k * sigma1d * sqrt(h), clamped
- cohorts are SEPARATE; fixed and dynamic results are never silently merged
- the legacy n≈133 is an archived burn-in epoch, excluded from headline metrics
- "Layer 3 = one hardcoded symbol" is replaced by experimental *flags*
- nothing here claims ARGUS is "learning"; it measures calibration only
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "calibration-v4"
UNIVERSE_VERSION = "regime_sensor_v2"        # v10.72: re-selected 16-sensor universe
TACTICAL_BENCHMARK_VERSION = "tactical_benchmark_v2"  # v10.72: diversified 14-equity benchmark
FACTOR_GROUP_VERSION = "factor_groups_v2"
SCORER_VERSION = "calib-scorer-1"
BAND_VERSION = "calib-band-1"
COHORT_VERSION = "calib-cohort-2"            # bumped with the v2 universe
# Legacy v1 universe (kept ONLY so legacy/burn-in records remain interpretable —
# never recompute old records under v2). v1 regime sensors included 8306/7203/
# 8058/9432 as JP sensors and USDJPY/VIX as scored sensors; v2 moves those to the
# tactical benchmark and to Context Variables respectively.
UNIVERSE_VERSION_LEGACY = "regime_sensor_v1"

# ── Ordered scenario classes (the 3-class forecast) ─────────────────────────
# Order matters for RPS (ranked probability score): downside < sideways < rebound.
CLASSES: Tuple[str, str, str] = (
    "downside_continuation",
    "sideways_stabilization",
    "rebound_attempt",
)
CLASS_INDEX = {c: i for i, c in enumerate(CLASSES)}

# ── Cohort model (replaces the old fixed "Layer 1/2/3") ─────────────────────
COHORT_REGIME_SENSOR = "regime_sensor_fixed"     # was Layer 1
COHORT_TACTICAL_FIXED = "tactical_benchmark_fixed"  # was Layer 2
COHORT_OWNER_WATCHLIST = "owner_watchlist_dynamic"  # new Layer 2B (private store)
COHORT_EXPERIMENTAL = "experimental_cohort"       # replaces "Layer 3 = 6584"

# Fixed regime-sensor universe v2 (16). Stable + versioned; does NOT follow the
# owner's daily interests. Context variables (USDJPY/VIX/yields/HY OAS) are NOT
# here — they are explanatory context, not equal return-scored securities.
REGIME_SENSORS: Tuple[str, ...] = (
    "1306", "1321", "1615", "1343",                              # JP (4)
    "SPY", "QQQ", "IWM", "SMH", "XLF", "XLE", "XLU",             # US equity/sector (7)
    "TLT", "LQD", "HYG", "GLD",                                  # bonds/credit/haven (4)
    "BTC",                                                       # crypto (1)
)
DISPLAY_NAMES: Dict[str, str] = {
    "1306": "TOPIX ETF", "1321": "日経225 ETF", "1615": "東証銀行業ETF",
    "1343": "東証REIT ETF", "SPY": "S&P500 ETF", "QQQ": "Nasdaq100 ETF",
    "IWM": "Russell2000 ETF", "SMH": "半導体ETF", "XLF": "米金融セクターETF",
    "XLE": "米エネルギーETF", "XLU": "米公益(ディフェンシブ)ETF",
    "TLT": "米長期国債ETF", "LQD": "米投資適格社債ETF", "HYG": "米ハイイールド債ETF",
    "GLD": "金ETF", "BTC": "ビットコイン",
    "8306": "三菱UFJ FG", "7203": "トヨタ自動車", "8058": "三菱商事",
    "9432": "日本電信電話(NTT)", "9984": "ソフトバンクグループ",
    "7011": "三菱重工業", "5803": "フジクラ", "NVDA": "NVIDIA", "AAPL": "Apple",
    "TSLA": "Tesla", "JPM": "JPMorgan Chase", "XOM": "Exxon Mobil",
    "PG": "Procter & Gamble", "CAT": "Caterpillar",
}

# Fixed tactical benchmark v2 (14) — diversified company types (not 4 correlated
# mega-cap growth names). NOT the owner's changing watchlist. 5803 フジクラ is
# intentionally the fixed Japan AI-infrastructure benchmark; 5801 and META are
# NOT here (they remain available via the owner dynamic watchlist).
TACTICAL_BENCHMARK: Tuple[str, ...] = (
    "8306", "7203", "8058", "9432", "9984", "7011", "5803",   # JP (7)
    "NVDA", "AAPL", "TSLA", "JPM", "XOM", "PG", "CAT",        # US (7)
)

# Layer-1 factor groups v2 — Layer-1 quality is aggregated by GROUP, never a flat
# equal-weight of 16 correlated symbols. 1306+1321 share jp_broad_equity (each
# gets half its weight) so Japan broad equity can't count twice.
FACTOR_GROUPS: Dict[str, Tuple[str, ...]] = {
    "jp_broad_equity": ("1306", "1321"),
    "jp_rates_banks": ("1615",),
    "jp_reit_rates": ("1343",),
    "us_broad_equity": ("SPY",),
    "us_growth": ("QQQ",),
    "us_small_cap": ("IWM",),
    "us_semiconductor": ("SMH",),
    "us_financials": ("XLF",),
    "us_energy": ("XLE",),
    "us_defensive": ("XLU",),
    "duration": ("TLT",),
    "investment_grade_credit": ("LQD",),
    "high_yield_credit": ("HYG",),
    "safe_haven": ("GLD",),
    "crypto_liquidity": ("BTC",),
}
_SYMBOL_FACTOR_GROUP = {s: g for g, syms in FACTOR_GROUPS.items() for s in syms}

# Tactical-benchmark factor roles (for 2A diversification reporting; orthogonal
# to the Layer-1 aggregation above).
TACTICAL_FACTOR_GROUPS: Dict[str, str] = {
    "8306": "jp_bank_rate_sensitive", "7203": "jp_export_fx_sensitive",
    "8058": "jp_trading_house_value", "9432": "jp_defensive_telecom",
    "9984": "jp_high_beta_technology", "7011": "jp_defense_capital_goods",
    "5803": "jp_ai_infrastructure_momentum",
    "NVDA": "us_ai_semiconductor", "AAPL": "us_quality_growth",
    "TSLA": "us_high_beta_event", "JPM": "us_financials", "XOM": "us_energy",
    "PG": "us_defensive_consumer", "CAT": "us_industrial_cyclical",
}

# Context Variables (section 3) — macro/market explanatory variables. NOT averaged
# as equal return-scored Layer-1 securities (VIX is inverse-risk, USDJPY is
# context-dependent, yields/HY OAS are rates/credit levels, not equity returns).
CONTEXT_VARIABLES: Dict[str, str] = {
    "fx_usdjpy": "USDJPY", "volatility_vix": "VIX",
    "rates_us10y": "US10Y", "rates_us2y": "US2Y",
    "rates_real10y": "US Real10Y", "credit_hy_oas": "HY OAS",
}

# Experimental flag vocabulary (section 5). 6584 migrates here instead of being
# a hardcoded "Layer 3". Flags are data-driven where data exists; manual flags
# must record flagSource=manual + evidence.
EXPERIMENTAL_FLAGS = (
    "newly_listed", "small_cap", "low_liquidity", "wide_spread",
    "high_volatility", "theme_driven", "event_driven", "limit_move_prone",
    "short_history", "data_quality_risk",
)

# Manual seed flags (flagSource=manual, with an explicit reason so they're
# auditable). Orthogonal to cohort membership. NOTE: 5803 is deliberately NOT
# here — it stays in the fixed tactical benchmark even if data-driven rules later
# add a high-volatility/theme tag to it.
_MANUAL_EXPERIMENTAL: Dict[str, Tuple[str, ...]] = {
    "6584": ("small_cap", "high_volatility", "event_driven"),  # 三櫻工業
    "9501": ("policy_sensitive", "event_driven"),              # 東京電力HD
    "285A": ("theme_driven",),                                  # キオクシア
    "5801": ("theme_driven", "high_volatility"),               # 古河電工 (2B-eligible)
}


def classify_cohort(symbol: str) -> str:
    """Map a symbol to its PRIMARY fixed cohort.

    Owner-watchlist (dynamic) membership is decided per-day by the sync layer
    (Phase 4), not here — this only resolves the fixed server-side cohorts.
    A symbol that is also experimentally flagged still keeps its primary cohort;
    experimental flags are an orthogonal tag (an asset can carry several).
    """
    s = (symbol or "").upper()
    if s in {x.upper() for x in REGIME_SENSORS}:
        return COHORT_REGIME_SENSOR
    if s in _MANUAL_EXPERIMENTAL:
        return COHORT_EXPERIMENTAL
    if s in {x.upper() for x in TACTICAL_BENCHMARK}:
        return COHORT_TACTICAL_FIXED
    return COHORT_EXPERIMENTAL  # unknown server-side names default to experimental


def cohort_memberships(symbol: str, owner_symbols: Optional[Sequence[str]] = None) -> List[str]:
    """ALL cohorts a symbol belongs to (overlap is allowed + expected).

    Overlap-safety invariant: a symbol may be in regime/tactical AND the owner
    watchlist at once. The recorder stores ONE immutable forecast per symbol/day
    and attaches MULTIPLE memberships — it must never fetch twice or emit two
    predictions for the same symbol. classify_cohort() still returns the single
    PRIMARY cohort (for the legacy per-row field); this returns the full set for
    cohort reports so overlaps are counted once globally but appear in each cohort.
    """
    s = (symbol or "").upper()
    owners = {x.upper() for x in (owner_symbols or [])}
    out: List[str] = []
    if s in {x.upper() for x in REGIME_SENSORS}:
        out.append(COHORT_REGIME_SENSOR)
    if s in {x.upper() for x in TACTICAL_BENCHMARK}:
        out.append(COHORT_TACTICAL_FIXED)
    if s in owners:
        out.append(COHORT_OWNER_WATCHLIST)
    if s in _MANUAL_EXPERIMENTAL:
        out.append(COHORT_EXPERIMENTAL)
    return out or [COHORT_EXPERIMENTAL]


def factor_group_of(symbol: str) -> Optional[str]:
    """Layer-1 sensor factor group, else the tactical-benchmark factor role."""
    s = (symbol or "").upper()
    return (_SYMBOL_FACTOR_GROUP.get(s) or _SYMBOL_FACTOR_GROUP.get(symbol or "")
            or TACTICAL_FACTOR_GROUPS.get(s) or TACTICAL_FACTOR_GROUPS.get(symbol or ""))


def context_variables() -> Dict[str, str]:
    """Context Variables (id → display). NOT equal return-scored Layer-1 assets."""
    return dict(CONTEXT_VARIABLES)


def display_name(symbol: str) -> Optional[str]:
    return DISPLAY_NAMES.get((symbol or "").upper()) or DISPLAY_NAMES.get(symbol or "")


def experimental_flags(
    symbol: str,
    *,
    realized_vol_pct: Optional[float] = None,
    vol_segment_p80: Optional[float] = None,
    turnover_yen: Optional[float] = None,
    turnover_floor_yen: Optional[float] = None,
    spread_bps: Optional[float] = None,
    spread_ceiling_bps: Optional[float] = None,
    sessions_listed: Optional[int] = None,
    min_sessions: int = 60,
    trailing_obs: Optional[int] = None,
    min_obs: int = 20,
) -> List[Dict[str, Any]]:
    """Return data-driven experimental flags for a symbol, plus any manual seeds.

    Only emits a flag when the *evidence is actually present* (never fabricates
    float ratio / spread / theme). Each flag records flagSource + evidence.
    """
    flags: List[Dict[str, Any]] = []

    def add(name: str, source: str, evidence: str) -> None:
        flags.append({
            "flag": name, "flagSource": source, "flagVersion": COHORT_VERSION,
            "evidence": evidence,
        })

    sym = (symbol or "").upper()
    for name in _MANUAL_EXPERIMENTAL.get(sym, ()):  # legacy seeds (auditable)
        add(name, "manual", "legacy Layer-3 designation (2026-06-11)")

    if realized_vol_pct is not None and vol_segment_p80 is not None and realized_vol_pct > vol_segment_p80:
        add("high_volatility", "automatic", f"realizedVol {realized_vol_pct:.2f}% > segP80 {vol_segment_p80:.2f}%")
    if turnover_yen is not None and turnover_floor_yen is not None and turnover_yen < turnover_floor_yen:
        add("low_liquidity", "automatic", f"turnover ¥{turnover_yen:.0f} < floor ¥{turnover_floor_yen:.0f}")
    if spread_bps is not None and spread_ceiling_bps is not None and spread_bps > spread_ceiling_bps:
        add("wide_spread", "automatic", f"spread {spread_bps:.1f}bps > ceil {spread_ceiling_bps:.1f}bps")
    if sessions_listed is not None and sessions_listed < min_sessions:
        add("newly_listed", "automatic", f"{sessions_listed} < {min_sessions} sessions")
    if trailing_obs is not None and trailing_obs < min_obs:
        add("short_history", "automatic", f"{trailing_obs} < {min_obs} obs")

    # de-dup (manual + automatic could both assert e.g. high_volatility)
    seen, out = set(), []
    for f in flags:
        if f["flag"] in seen:
            continue
        seen.add(f["flag"])
        out.append(f)
    return out


# ── Volatility bands (section 8): no-lookahead, sqrt-horizon scaling ─────────
# Asset-class clamps (in % of price) so a dead-flat sensor doesn't get a 0 band
# and a wild one doesn't get an absurd band. Crypto/FX/vol have their own scale.
_BAND_CLAMPS = {
    "equity": (0.8, 6.0),
    "etf": (0.5, 5.0),
    "crypto": (1.5, 15.0),
    "fx": (0.2, 2.5),
    "vol": (3.0, 25.0),
}
_BAND_K = 1.0  # band = k * sigma1d * sqrt(h); k versioned with BAND_VERSION


# All regime sensors except BTC are ETFs — derive the set so newly-added sensors
# (1615/1343/XLF/XLE/XLU/LQD …) get ETF vol bands automatically (GPT #5 fix:
# they were silently classified as single-equity before).
_ETF_SYMBOLS = frozenset(s.upper() for s in REGIME_SENSORS if s != "BTC")


def _asset_kind(symbol: str) -> str:
    s = (symbol or "").upper()
    if s == "VIX":
        return "vol"
    if s == "USDJPY" or s.endswith("=X"):
        return "fx"
    if s in ("BTC", "ETH", "SOL"):
        return "crypto"
    if s in _ETF_SYMBOLS:
        return "etf"
    return "equity"


def realized_vol_pct(closes: Sequence[float]) -> Optional[float]:
    """Trailing close-to-close 1-day realized volatility (% of price), sample std.

    Uses ONLY the provided history (caller must pass pre-forecast closes — no
    lookahead). Returns None if there is insufficient history (<2 returns).
    """
    px = [float(c) for c in closes if c is not None and float(c) > 0]
    if len(px) < 3:
        return None
    rets = [(px[i] - px[i - 1]) / px[i - 1] for i in range(1, len(px))]
    n = len(rets)
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / (n - 1)
    return math.sqrt(var) * 100.0


def volatility_band(
    symbol: str,
    closes: Sequence[float],
    horizon_days: int = 1,
    *,
    window: int = 20,
) -> Dict[str, Any]:
    """Compute the ± band (% of price) for a symbol at a given horizon.

    band(h) = k * sigma1d * sqrt(h), clamped to the asset-class range. Falls back
    to the clamp midpoint when history is insufficient (fallbackUsed=True).
    """
    kind = _asset_kind(symbol)
    lo_clamp, hi_clamp = _BAND_CLAMPS[kind]
    used = list(closes)[-(window + 1):] if window else list(closes)
    sigma = realized_vol_pct(used)
    fallback = sigma is None
    if fallback:
        band = (lo_clamp + hi_clamp) / 2.0
        reason = "insufficient_history"
        sample = max(0, len(used) - 1)
    else:
        band = _BAND_K * sigma * math.sqrt(max(1, horizon_days))
        band = max(lo_clamp, min(hi_clamp, band))
        reason = None
        sample = len(used) - 1
    return {
        "bandPctUsed": round(band, 4),
        "lowerBand": round(-band, 4),
        "upperBand": round(band, 4),
        "bandMethod": "trailing_realized_vol_sqrt_h",
        "bandVersion": BAND_VERSION,
        "volatilityWindow": window,
        "volatilitySampleCount": sample,
        "fallbackUsed": fallback,
        "fallbackReason": reason,
    }


def score_prediction(scenarios: Dict[str, float], price_at: Optional[float],
                     realized_price: Optional[float], band_pct: float) -> Optional[Dict[str, Any]]:
    """Score one scenario forecast against a realized price. scenarios may be any
    scale (normalized internally). Returns realized class + Brier + RPS + argmax,
    or None if prices are unusable. Pure — used by the Layer 2B daily scorer."""
    if not price_at or price_at <= 0 or realized_price is None:
        return None
    move = (realized_price - price_at) / price_at * 100.0
    realized = classify_realized(move, band_pct)
    out = {"movePct": round(move, 4), "realizedClass": realized,
           "argmaxHit": argmax_hit(scenarios, realized)}
    out.update(brier_multiclass(scenarios, realized))
    out.update(rps(scenarios, realized))
    return out


def classify_realized(move_pct: float, band_pct: float) -> str:
    """Map a realized return to its ordered class given the band."""
    if move_pct < -abs(band_pct):
        return "downside_continuation"
    if move_pct > abs(band_pct):
        return "rebound_attempt"
    return "sideways_stabilization"


# ── Scoring (section 9): proper rules primary, argmax auxiliary ──────────────
def _as_dist(probs: Dict[str, float]) -> List[float]:
    """Normalize a {class: p} dict to an ordered, summing-to-1 list. Non-finite
    (NaN/Inf) and negative inputs are treated as 0 (GPT fix: reject bad floats)."""
    raw = []
    for c in CLASSES:
        try:
            v = float(probs.get(c, 0.0))
        except (TypeError, ValueError):
            v = 0.0
        raw.append(v if (math.isfinite(v) and v > 0) else 0.0)
    s = sum(raw)
    if s <= 0:
        return [1.0 / len(CLASSES)] * len(CLASSES)
    return [r / s for r in raw]


def brier_multiclass(probs: Dict[str, float], realized_class: str) -> Dict[str, float]:
    """Multiclass Brier. Lower is better.

    brierRawSum       = Σ_k (p_k - o_k)^2     range 0 .. 2
    brierNormalizedMean = raw / K             range 0 .. 2/K  (≈0.667 for K=3)
    (NOT 0..1 — divide raw by 2 if you need a 0..1 scale.)
    """
    p = _as_dist(probs)
    o = [1.0 if c == realized_class else 0.0 for c in CLASSES]
    raw = sum((p[i] - o[i]) ** 2 for i in range(len(CLASSES)))
    return {"brierRawSum": round(raw, 6), "brierNormalizedMean": round(raw / len(CLASSES), 6)}


def rps(probs: Dict[str, float], realized_class: str) -> Dict[str, float]:
    """Ranked Probability Score for ORDERED classes. Lower is better.

    RPS = Σ_{k=1}^{K-1} ( Σ_{j<=k} (p_j - o_j) )^2 ; normalized by (K-1).
    """
    p = _as_dist(probs)
    o = [1.0 if c == realized_class else 0.0 for c in CLASSES]
    cum_p = cum_o = 0.0
    total = 0.0
    for k in range(len(CLASSES) - 1):
        cum_p += p[k]
        cum_o += o[k]
        total += (cum_p - cum_o) ** 2
    return {"rpsRaw": round(total, 6), "rpsNormalized": round(total / (len(CLASSES) - 1), 6)}


def argmax_hit(probs: Dict[str, float], realized_class: str) -> bool:
    p = _as_dist(probs)
    pred_idx = max(range(len(CLASSES)), key=lambda i: p[i])
    return CLASSES[pred_idx] == realized_class


def directional_hit(probs: Dict[str, float], realized_class: str) -> Optional[bool]:
    """Directional accuracy: collapse to down / not-down vs up / not-up.

    Returns None when the forecast's argmax is 'sideways' (no directional call).
    """
    p = _as_dist(probs)
    pred = CLASSES[max(range(len(CLASSES)), key=lambda i: p[i])]
    if pred == "sideways_stabilization":
        return None
    if pred == "downside_continuation":
        return realized_class == "downside_continuation"
    return realized_class == "rebound_attempt"


def skill_score(model_score: float, baseline_score: float) -> Optional[float]:
    """1 - model/baseline (for proper scores where lower is better).

    >0 means the model beats the baseline. None if baseline is ~0 (undefined).
    """
    if baseline_score is None or abs(baseline_score) < 1e-9:
        return None
    return round(1.0 - (model_score / baseline_score), 6)


# ── Baselines (section 10): use only pre-forecast info ───────────────────────
def baseline_naive_sideways() -> Dict[str, float]:
    return {"downside_continuation": 0.0, "sideways_stabilization": 1.0, "rebound_attempt": 0.0}


def baseline_climatology(prior_realized: Sequence[str]) -> Dict[str, Any]:
    """Expanding climatology from PRIOR realized classes (no future leakage)."""
    counts = {c: 0 for c in CLASSES}
    for r in prior_realized:
        if r in counts:
            counts[r] += 1
    n = sum(counts.values())
    if n == 0:
        dist = {c: 1.0 / len(CLASSES) for c in CLASSES}
        return {"dist": dist, "sampleCount": 0, "fallback": "no_history"}
    return {"dist": {c: counts[c] / n for c in CLASSES}, "sampleCount": n, "fallback": None}


def baseline_prev_day_momentum(prev_return_pct: Optional[float], band_pct: float) -> Dict[str, float]:
    """Versioned mapping: yesterday's direction → today's class probabilities."""
    if prev_return_pct is None:
        return {"downside_continuation": 1 / 3, "sideways_stabilization": 1 / 3, "rebound_attempt": 1 / 3}
    if prev_return_pct > abs(band_pct):
        return {"downside_continuation": 0.20, "sideways_stabilization": 0.30, "rebound_attempt": 0.50}
    if prev_return_pct < -abs(band_pct):
        return {"downside_continuation": 0.50, "sideways_stabilization": 0.30, "rebound_attempt": 0.20}
    return {"downside_continuation": 0.25, "sideways_stabilization": 0.50, "rebound_attempt": 0.25}


# ── Epochs (section 6) + reliability staging (section 13) ────────────────────
BURN_IN_EPOCH = "burn_in_legacy_v3"
ACTIVE_EPOCH = "calibration_v1"


def burn_in_epoch_record(date_range: Tuple[Optional[str], Optional[str]], record_count: int) -> Dict[str, Any]:
    """The archival descriptor for the legacy n≈133 — preserved, not deleted."""
    return {
        "epochId": BURN_IN_EPOCH,
        "status": "archived_unstable",
        "includeInHeadlineMetrics": False,
        "recordCount": record_count,
        "dateRange": {"from": date_range[0], "to": date_range[1]},
        "reason": [
            "unstable provider coverage", "ledger recovery period",
            "incomplete sensors", "pre-final cohort definition",
            "legacy timing/band/scoring rules",
        ],
    }


def reliability_stage(trading_day_count: int) -> str:
    """Honest staging — never 'proven'."""
    if trading_day_count < 30:
        return "burn_in"
    if trading_day_count < 60:
        return "early_signal"
    if trading_day_count < 120:
        return "provisional"
    return "regime_level"


def readiness_check(
    *,
    required_sensor_coverage: float,
    layer1_session_coverage: float,
    rolling_per_sensor_coverage: float,
    unresolved_write_failures: int,
    stale_price_forecasts: int,
    cohorts_finalized: bool,
    scoring_tests_pass: bool,
) -> Dict[str, Any]:
    """Gate for activating the clean epoch. Tolerant of ONE optional provider
    failing forever (does not demand 16/16 every day), but strict on essentials.
    """
    checks = {
        "required_sensors_100pct": required_sensor_coverage >= 1.0,
        "layer1_coverage_min_15_16": layer1_session_coverage >= (15.0 / 16.0),
        "rolling_per_sensor_min_90pct": rolling_per_sensor_coverage >= 0.90,
        "no_unresolved_write_failures": unresolved_write_failures == 0,
        "no_stale_price_forecasts": stale_price_forecasts == 0,
        "cohort_definitions_finalized": cohorts_finalized,
        "scoring_tests_pass": scoring_tests_pass,
    }
    return {
        "ready": all(checks.values()),
        "checks": checks,
        "activeEpoch": ACTIVE_EPOCH,
        "note": "activation is a separate admin step; epochs never auto-start",
    }


# ── Factor-group-weighted Layer-1 aggregate (section 14) ─────────────────────
def factor_group_aggregate(per_symbol_scores: Dict[str, float]) -> Dict[str, Any]:
    """Aggregate sensor scores by factor group (equal group weight), so the 3
    correlated US-equity sensors don't dominate the Layer-1 headline.
    """
    group_scores: Dict[str, float] = {}
    group_members: Dict[str, List[str]] = {}
    for sym, score in per_symbol_scores.items():
        g = factor_group_of(sym)
        if not g:
            continue
        group_members.setdefault(g, []).append(sym)
    for g, members in group_members.items():
        vals = [per_symbol_scores[m] for m in members]
        group_scores[g] = sum(vals) / len(vals)
    overall = (sum(group_scores.values()) / len(group_scores)) if group_scores else None
    return {
        "factorGroupScores": {g: round(v, 6) for g, v in group_scores.items()},
        "overallEqualGroupWeighted": round(overall, 6) if overall is not None else None,
        "factorGroupVersion": FACTOR_GROUP_VERSION,
    }
