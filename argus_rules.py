"""ARGUS pure scoring layer (argus_rules.py, extracted v10.37, #9 phase 1).

Leaf-pure domain logic for the entry scout: technical metrics, gap detection,
margin / 日証金 / disclosed-short reads, probabilistic flow inference, the
score assessment, and the call/narrative composer. NO Flask, NO network, NO
module-level cache — only stdlib + each other, so scanner.py imports these back
and behavior is unchanged. Unit-tested by test_rules.py.
"""
import math  # noqa: F401  (used by some scoring helpers)

def _margin_signal(rows):
    """Pure (unit-tested): newest-first weekly margin rows → a short-covering /
    fresh-buying read. None when <2 weeks. Credit ratio = long/short (>1 買い長,
    <1 売り長). Week-over-week deltas reveal which side is building."""
    if not rows or len(rows) < 2:
        return None
    cur, prev = rows[0], rows[1]
    long_v, short_v = cur["longVol"], cur["shortVol"]
    ratio = round(long_v / short_v, 2) if short_v else None
    d_long = (long_v - prev["longVol"]) / prev["longVol"] * 100 if prev["longVol"] else 0.0
    d_short = (short_v - prev["shortVol"]) / prev["shortVol"] * 100 if prev["shortVol"] else 0.0
    return {
        "date": cur["date"], "creditRatio": ratio,
        "longVol": long_v, "shortVol": short_v,
        "longWoWPct": round(d_long, 1), "shortWoWPct": round(d_short, 1),
    }

def _margin_assess_lines(sig):
    """Pure: margin signal → (score_delta, reasonsJa[]). Short-covering fuel is
    a tailwind; ballooning long balance is overhang. All contributions visible."""
    if not sig:
        return 0.0, []
    score, reasons = 0.0, []
    r = sig.get("creditRatio")
    if isinstance(r, (int, float)):
        if r < 1.0:
            score += 0.5
            reasons.append(f"信用倍率{r}倍(売り長) — 買い戻し(踏み上げ)の余地")
        elif r >= 5.0:
            score -= 0.5
            reasons.append(f"信用倍率{r}倍(買い長) — 上値に戻り売り圧力")
    if sig.get("shortWoWPct", 0) >= 15:
        score += 0.5
        reasons.append(f"信用売り残が前週比+{sig['shortWoWPct']}% — 将来の買い戻し圧力が蓄積")
    if sig.get("longWoWPct", 0) >= 15:
        score -= 0.5
        reasons.append(f"信用買い残が前週比+{sig['longWoWPct']}% — 新規買いの過熱(戻り売り予備軍)")
    return score, reasons

def _short_disclosed_assess(sd):
    """Pure (unit-tested): disclosed institutional short → (score_delta,
    reasonsJa[]). Heavy disclosed short is squeeze FUEL if price turns — but
    also reflects strong bearish conviction, so the wording says both and the
    score nudge is modest."""
    if not sd or not sd.get("ratio"):
        return 0.0, []
    pct = round(sd["ratio"] * 100, 1)
    n = sd.get("reporters", 0)
    if sd["ratio"] >= 0.05:
        return 0.5, [f"機関の大口空売り残 {pct}%({n}者) — 反転すれば強い踏み上げ燃料(弱気確信の裏返しでもある)"]
    if sd["ratio"] >= 0.02:
        return 0.3, [f"機関の大口空売り残 {pct}%({n}者) — 買い戻し余地あり(両面解釈)"]
    return 0.0, [f"機関の大口空売り残 {pct}%({n}者・小規模)"]

def _flow_inference(m, flow_ratio, jsf, short_disclosed):
    """Pure (unit-tested): fuse the in-hand 需給 signals into a PROBABILISTIC
    read of WHO is moving the stock — new buying vs short-covering vs
    distribution vs retail noise. Never a certainty (ChatGPT/Gemini both
    stress this is impossible from external data); confidence drops when data
    is thin, and VWAP/orderbook gaps are stated. Adopted from the 2026-06-13
    Gemini+GPT consult, built only on data ARGUS already fetches."""
    w = {"newLong": 0.0, "shortCovering": 0.0, "distribution": 0.0, "retailNoise": 0.0}
    reasons, have = [], 0
    ret1 = m.get("ret1") or 0.0
    ret5 = m.get("ret5") or 0.0
    ret20 = m.get("ret20") or 0.0
    volr = m.get("volRatio5v20")
    up = ret1 > 0 or ret5 > 0

    if jsf:
        have += 1
        sn, sr = jsf.get("shortNew") or 0, jsf.get("shortRepay") or 0
        ln, lr = jsf.get("loanNew") or 0, jsf.get("loanRepay") or 0
        ratio = jsf.get("ratio")
        if up and (sr - sn) > max(1, sr * 0.1):       # short balance shrinking
            w["shortCovering"] += 2.0
            reasons.append("株価上昇中に貸株残が縮小(返済>新規)= 買い戻しが進行")
        if up and (ln - lr) > max(1, lr * 0.1):       # margin longs building
            w["newLong"] += 1.5
            reasons.append("融資残が増加(新規>返済)= 新規の信用買いが流入")
        if (lr - ln) > max(1, ln * 0.1) and not up:   # longs unwinding, no rise
            w["distribution"] += 1.0
            reasons.append("信用買い方が返済超(利食い/手仕舞い)= 上値が重い")
        if isinstance(ratio, (int, float)) and ratio < 1.0:
            w["shortCovering"] += 1.0
            reasons.append(f"日証金倍率{ratio}(売り長)= 踏み上げ燃料が残存")
    if short_disclosed and short_disclosed.get("ratio"):
        have += 1
        sd = short_disclosed["ratio"]
        if sd >= 0.05:
            w["shortCovering"] += 1.5
            reasons.append(f"機関の大口空売り{round(sd*100,1)}% = 買い戻し燃料が大きい")
    if isinstance(flow_ratio, (int, float)):
        have += 1
        if flow_ratio >= 0.15 and up:
            w["newLong"] += 1.0
            reasons.append(f"大口資金が純流入+{round(flow_ratio*100)}%(当日)")
        elif flow_ratio <= -0.15:
            w["distribution"] += 1.5
            reasons.append(f"大口資金が純流出{round(flow_ratio*100)}%(上で売り抜けの疑い)")
    if isinstance(volr, (int, float)) and volr >= 1.5:
        have += 1
        if not up:
            w["distribution"] += 1.0
            reasons.append(f"出来高{volr}倍だが株価が伴わない(分配の疑い)")
        elif ret20 > 0 and ret5 > 0:
            w["newLong"] += 0.5
            reasons.append("出来高増+中期(20日)上昇が継続")
    # A sharp one-day spike with no credit fuel reads as retail/news noise.
    if ret1 >= 4 and not (jsf and isinstance(jsf.get("ratio"), (int, float)) and jsf["ratio"] < 1):
        w["retailNoise"] += 0.5
        reasons.append("短期急騰だが信用の買い戻し燃料が乏しい(個人・テーマ性ノイズの可能性)")

    LABEL = {"newLong": "NEW_LONG_ACCUMULATION", "shortCovering": "SHORT_COVERING",
             "distribution": "DISTRIBUTION", "retailNoise": "RETAIL_NOISE"}
    total = sum(w.values())
    limits = ["VWAP・板・歩み値が未接続のため日中のリアルタイム・フローは見えない(推定精度は限定的)",
              "制度信用以外(一般信用・海外勢・ヘッジ)のポジションは見えない",
              "注文主の内部IDは取得不可 — 断定ではなく確率推定"]
    nxt = ("翌営業日も上昇が続き出来高を伴えば新規買い寄りに更新。"
           "続かず貸株残が急減し出来高が細れば買い戻し一巡とみなす。")
    if total == 0 or have < 2:
        return {"classification": "UNCONFIRMED",
                "probabilities": {"newLongAccumulation": 0.0, "shortCovering": 0.0,
                                  "distribution": 0.0, "retailNoise": 0.0, "unconfirmed": 1.0},
                "confidence": "low", "reasonsJa": reasons or ["判定に十分な需給データが揃っていません。"],
                "nextConditionJa": nxt, "dataLimitationsJa": limits}
    # More independent sources → less reserved for "unconfirmed".
    unconf = max(0.05, round(0.45 - 0.1 * have, 2))
    scale = (1.0 - unconf) / total
    probs = {
        "newLongAccumulation": round(w["newLong"] * scale, 2),
        "shortCovering": round(w["shortCovering"] * scale, 2),
        "distribution": round(w["distribution"] * scale, 2),
        "retailNoise": round(w["retailNoise"] * scale, 2),
        "unconfirmed": unconf,
    }
    top = max(w, key=w.get)
    # Squeeze-risk nuance: covering is the call AND fuel still remains.
    cls = LABEL[top]
    if cls == "SHORT_COVERING" and ((jsf and (jsf.get("ratio") or 9) < 1)
                                    or (short_disclosed and short_disclosed.get("ratio", 0) >= 0.05)):
        reasons.insert(0, "踏み上げ継続リスク: 買い戻し燃料がまだ残っている")
    return {"classification": cls, "probabilities": probs,
            "confidence": "medium" if have >= 3 else "low",
            "reasonsJa": reasons, "nextConditionJa": nxt, "dataLimitationsJa": limits}

def _jsf_assess_lines(j):
    """Pure (unit-tested): JSF daily balance → (score_delta, reasonsJa[]).
    日証金倍率(融資残/貸株残): <1 売り長=踏み上げ燃料(+), 高倍率=買い長で戻り売り(-).
    Plus today's new-vs-repayment direction. All contributions visible."""
    if not j:
        return 0.0, []
    score, reasons = 0.0, []
    r = j.get("ratio")
    if isinstance(r, (int, float)):
        if r < 1.0:
            score += 0.5
            reasons.append(f"日証金倍率{r}倍(貸株超=売り長) — 買い戻し(踏み上げ)の燃料")
        elif r >= 3.0:
            score -= 0.5
            reasons.append(f"日証金倍率{r}倍(融資超=買い長) — 上値に戻り売り圧力")
    sn, sr = j.get("shortNew"), j.get("shortRepay")
    if isinstance(sn, int) and isinstance(sr, int) and sn > sr * 1.3 and sn > 0:
        score += 0.3
        reasons.append("本日の新規売り>返済 — 売り建てが増加(将来の買い戻し余地)")
    ln, lr = j.get("loanNew"), j.get("loanRepay")
    if isinstance(ln, int) and isinstance(lr, int) and ln > lr * 1.3 and ln > 0:
        score -= 0.3
        reasons.append("本日の新規買い建てが増加 — 短期の買い疲れに注意")
    return score, reasons

def _detect_gap(closes, highs, lows):
    """Pure (unit-tested): most recent price gap (窓) in the last ~5 sessions,
    newest-first. Gap up = today's low > prior high; gap down = today's high <
    prior low. Returns {dir, pct, sessionsAgo, filled} or None. Needs H/L —
    returns None when unavailable (no faking)."""
    if not highs or not lows or len(closes) < 3:
        return None
    # Minimum gap size to count as a real 窓 — below this it is just tick/round
    # noise (verified: 8058 showed a meaningless +0.04% "gap"), not a level.
    MIN_GAP_PCT = 0.5
    for i in range(min(5, len(closes) - 1)):
        hi_today, lo_today = highs[i], lows[i]
        hi_prev, lo_prev = highs[i + 1], lows[i + 1]
        if None in (hi_today, lo_today, hi_prev, lo_prev):
            continue
        if lo_today > hi_prev:        # gap up
            gap_pct = round((lo_today - hi_prev) / hi_prev * 100, 2)
            if gap_pct < MIN_GAP_PCT:
                continue
            filled = any(lows[j] is not None and lows[j] <= hi_prev for j in range(i))
            return {"dir": "up", "pct": gap_pct, "sessionsAgo": i, "filled": filled}
        if hi_today < lo_prev:        # gap down
            gap_pct = round((hi_today - lo_prev) / lo_prev * 100, 2)
            if abs(gap_pct) < MIN_GAP_PCT:
                continue
            filled = any(highs[j] is not None and highs[j] >= lo_prev for j in range(i))
            return {"dir": "down", "pct": gap_pct, "sessionsAgo": i, "filled": filled}
    return None

def _entry_metrics(closes, volumes=None, highs=None, lows=None):
    """Pure (unit-tested): trend/overheat metrics from NEWEST-FIRST closes.
    <20 sessions → None (too little history to say anything honest)."""
    if not closes or len(closes) < 20:
        return None
    c0 = closes[0]
    def ret(n):
        return round((c0 - closes[n]) / closes[n] * 100, 2) if len(closes) > n and closes[n] else None
    def ma(n):
        return sum(closes[:n]) / n if len(closes) >= n else None
    ma5, ma25 = ma(5), ma(25)
    gains = losses = 0.0
    for i in range(min(14, len(closes) - 1)):
        d = closes[i] - closes[i + 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    rsi = round(100 * gains / (gains + losses), 1) if (gains + losses) > 0 else 50.0
    consec_down = 0
    for i in range(len(closes) - 1):
        if closes[i] < closes[i + 1]:
            consec_down += 1
        else:
            break
    window = closes[:60]
    hi60, lo60 = max(window), min(window)
    vol_ratio = None
    if volumes and len(volumes) >= 25:
        v5 = sum(volumes[:5]) / 5
        v20 = sum(volumes[5:25]) / 20
        vol_ratio = round(v5 / v20, 2) if v20 else None
    # v2.1 (2026-06-13 「RSIやMACDも統合できているのか」): MACD(12,26,9)、
    # 移動平均クロス、ボリンジャー%b — all computed chronologically.
    chron = closes[::-1]                      # oldest-first

    def _ema(vals, n):
        k = 2.0 / (n + 1)
        e = vals[0]
        out = [e]
        for v in vals[1:]:
            e = v * k + e * (1 - k)
            out.append(e)
        return out

    macd_hist, macd_cross = None, None
    if len(chron) >= 35:
        e12, e26 = _ema(chron, 12), _ema(chron, 26)
        macd_line = [a - b for a, b in zip(e12, e26)]
        signal = _ema(macd_line, 9)
        hist = [a - b for a, b in zip(macd_line, signal)]
        macd_hist = round(hist[-1], 3)
        recent, before = hist[-1], hist[-4:-1]
        if recent > 0 and any(h <= 0 for h in before):
            macd_cross = "golden"
        elif recent < 0 and any(h >= 0 for h in before):
            macd_cross = "dead"

    def _sma_at(idx_from_end, n):
        seg = chron[max(0, len(chron) - idx_from_end - n):len(chron) - idx_from_end]
        return sum(seg) / len(seg) if len(seg) == n else None

    ma_cross = None
    ma5_now, ma25_now = _sma_at(0, 5), _sma_at(0, 25)
    ma5_prev, ma25_prev = _sma_at(5, 5), _sma_at(5, 25)
    if None not in (ma5_now, ma25_now, ma5_prev, ma25_prev):
        if ma5_now > ma25_now and ma5_prev <= ma25_prev:
            ma_cross = "golden"
        elif ma5_now < ma25_now and ma5_prev >= ma25_prev:
            ma_cross = "dead"

    boll_pct_b = None
    if len(closes) >= 25:
        seg = closes[:25]
        mean = sum(seg) / 25
        var = sum((x - mean) ** 2 for x in seg) / 25
        sd = var ** 0.5
        if sd > 0:
            boll_pct_b = round((c0 - (mean - 2 * sd)) / (4 * sd), 2)

    return {
        "ret1": ret(1), "ret5": ret(5), "ret20": ret(20),
        "ret60": ret(60) if len(closes) > 60 else None,
        "ma5DiffPct": round((c0 - ma5) / ma5 * 100, 2) if ma5 else None,
        "ma25DiffPct": round((c0 - ma25) / ma25 * 100, 2) if ma25 else None,
        "rsi14": rsi, "consecDown": consec_down,
        "offHigh60Pct": round((c0 - hi60) / hi60 * 100, 2) if hi60 else None,
        "offLow60Pct": round((c0 - lo60) / lo60 * 100, 2) if lo60 else None,
        "volRatio5v20": vol_ratio, "sessions": len(closes),
        "macdHist": macd_hist, "macdCross": macd_cross,
        "maCross": ma_cross, "bollPctB": boll_pct_b,
        "gap": _detect_gap(closes, highs, lows),
    }

def _entry_scout_assess(m, flow_ratio, esc, posture, vix_zone, weekday,
                        regime_label=None, vix_spike=False, rel_strength=None,
                        earnings_days=None, ai_view=None, margin_sig=None, jsf_sig=None,
                        short_disclosed=None):
    """Pure (unit-tested): metrics + context → stance/score/reasons. Every
    contribution is ±0.5〜1 AND stated in reasonsJa — no hidden weights. The
    Friday-bounce anomaly is NOTED but not scored (経験則 — the ledger will
    verify it with data before it earns score weight).
    v2 (2026-06-13 user: 「全能力をここに集約しろ」): regime, VIX spike,
    index-relative strength, earnings proximity, AI double-check view."""
    reasons, score = [], 0.0
    if m["ma25DiffPct"] is not None:
        if m["ma25DiffPct"] <= -8:
            score += 1; reasons.append(f"25日線から{m['ma25DiffPct']}%の下方乖離(売られすぎ圏)")
        elif m["ma25DiffPct"] >= 8:
            score -= 1; reasons.append(f"25日線から+{m['ma25DiffPct']}%の上方乖離(過熱圏)")
    if m["rsi14"] <= 30:
        score += 1; reasons.append(f"RSI14={m['rsi14']}(売られすぎ)")
    elif m["rsi14"] >= 70:
        score -= 1; reasons.append(f"RSI14={m['rsi14']}(買われすぎ)")
    if m["consecDown"] >= 3:
        score += 0.5; reasons.append(f"{m['consecDown']}日続落(自律反発の余地)")
    if (m["ret20"] or 0) > 0 and (m["ret5"] or 0) < 0:
        score += 0.5; reasons.append("中期(20日)上昇トレンド+短期(5日)押し目の形")
    if (m["volRatio5v20"] or 0) >= 1.5:
        reasons.append(f"出来高が平常の{m['volRatio5v20']}倍(注目度上昇 — 方向はフローで判断)")
    # v2.1: classic technicals — each ±0.5, all visible.
    if m.get("macdCross") == "golden":
        score += 0.5; reasons.append("MACDが直近で好転(シグナル線を上抜け)")
    elif m.get("macdCross") == "dead":
        score -= 0.5; reasons.append("MACDが直近で悪化(シグナル線を下抜け)")
    if m.get("maCross") == "golden":
        score += 0.5; reasons.append("5日線が25日線を上抜け(ゴールデンクロス)")
    elif m.get("maCross") == "dead":
        score -= 0.5; reasons.append("5日線が25日線を下抜け(デッドクロス)")
    b = m.get("bollPctB")
    if isinstance(b, (int, float)):
        if b <= 0:
            score += 0.5; reasons.append(f"ボリンジャー-2σ圏(%b={b}) — 統計的売られすぎ")
        elif b >= 1:
            score -= 0.5; reasons.append(f"ボリンジャー+2σ圏(%b={b}) — 統計的過熱")
    g = m.get("gap")
    if isinstance(g, dict):
        when = "本日" if g["sessionsAgo"] == 0 else f"{g['sessionsAgo']}日前"
        if g["dir"] == "up":
            if not g["filled"]:
                score += 0.3
            reasons.append(f"{when}に上放れの窓+{g['pct']}%({'未' if not g['filled'] else '埋め'}) — "
                           + ("下値支持として意識" if not g["filled"] else "窓埋め済み"))
        else:
            if not g["filled"]:
                score -= 0.3
            reasons.append(f"{when}に下放れの窓{g['pct']}%({'未' if not g['filled'] else '埋め'}) — "
                           + ("上値抵抗として意識" if not g["filled"] else "窓埋め済み"))
    if isinstance(flow_ratio, (int, float)):
        if flow_ratio >= 0.15:
            score += 1; reasons.append(f"大口資金が純流入+{round(flow_ratio * 100)}%(確証シグナル)")
        elif flow_ratio <= -0.15:
            score -= 1; reasons.append(f"大口資金が純流出{round(flow_ratio * 100)}%")
    if esc in ("D", "D-1"):
        score -= 1; reasons.append(f"重要イベント接近({esc}) — 結果待ちが原則")
    if posture == "elevated":
        score -= 0.5; reasons.append("金利地合いが逆風(elevated)")
    if vix_zone in ("elevated", "shock"):
        score -= 1; reasons.append(f"ボラティリティ圏域が{vix_zone}")
    # ── v2 factors ──
    if regime_label in ("RISK_OFF", "EVENT_WAIT"):
        score -= 1; reasons.append(f"市場レジームが{regime_label}(逆風の地合い)")
    elif regime_label == "RISK_ON":
        score += 0.5; reasons.append("市場レジームがRISK_ON(追い風)")
    if vix_spike:
        score -= 1; reasons.append("VIXが急騰中(パニック局面 — 入るならサイズを落とす)")
    if isinstance(rel_strength, (int, float)):
        if rel_strength >= 1.0:
            score += 0.5; reasons.append(f"指数(TOPIX)より{rel_strength:+.1f}pt強い(相対力あり)")
        elif rel_strength <= -1.0:
            score -= 0.5; reasons.append(f"指数(TOPIX)より{rel_strength:+.1f}pt弱い(相対的に売られている)")
    if isinstance(earnings_days, (int, float)):
        if 0 <= earnings_days <= 3:
            score -= 1; reasons.append(f"決算が{int(earnings_days)}日以内 — 結果は読めない(ギャンブル領域)")
        elif earnings_days <= 7:
            reasons.append(f"決算まで{int(earnings_days)}日(イベント前の建玉は軽めが原則)")
    if ai_view == "confirm":
        score += 0.5; reasons.append("AI二重チェック(GPT-5.5+Gemini)がルール判定に同意")
    elif ai_view == "disagree":
        score -= 1; reasons.append("AI二重チェックがルール判定に不同意(慎重化)")
    elif ai_view == "caution":
        score -= 0.5; reasons.append("AI二重チェックが注意を表明")
    # ── v2.2: weekly margin (信用残) — short-covering vs fresh-buying read ──
    ms_score, ms_reasons = _margin_assess_lines(margin_sig)
    score += ms_score; reasons.extend(ms_reasons)
    # ── v2.3: 日証金(JSF)daily 貸借残 — free alternative, works without plan ──
    js_score, js_reasons = _jsf_assess_lines(jsf_sig)
    score += js_score; reasons.extend(js_reasons)
    # ── v2.4: JPX disclosed institutional short (≥0.5%) — squeeze intel ──
    sd_score, sd_reasons = _short_disclosed_assess(short_disclosed)
    score += sd_score; reasons.extend(sd_reasons)
    if weekday == 4:
        reasons.append("金曜: 週末リスクで売られやすい日(翌営業日反発は経験則 — 台帳で検証中のため点数化はしない)")
    if score >= 1.5:
        stance = "攻め好機(候補)"
    elif score >= 0.5:
        stance = "押し目買い検討圏"
    elif score > -1:
        stance = "中立(急がない)"
    else:
        stance = "見送り"
    return {"stance": stance, "score": round(score, 2), "reasonsJa": reasons}

_CALL_BY_STANCE = {
    "攻め好機(候補)": "買い場(候補)",
    "押し目買い検討圏": "押し目買い検討",
    "中立(急がない)": "様子見(急がない)",
    "見送り": "見送り",
}

_FLOW_SHORT = {"SHORT_COVERING": "買い戻し主導", "NEW_LONG_ACCUMULATION": "新規買い流入",
               "DISTRIBUTION": "売り抜け疑い", "RETAIL_NOISE": "個人ノイズ"}

_FLOW_STORY = {
    "SHORT_COVERING": "大口は買い戻し主導の疑い(踏み上げ燃料が残存)",
    "NEW_LONG_ACCUMULATION": "新規の買いが入っている兆候(融資残増/大口純流入)",
    "DISTRIBUTION": "上値で売り抜けの疑い(大口純流出/信用の手仕舞い)",
    "RETAIL_NOISE": "個人・テーマ性の短期ノイズの可能性(信用の裏付けが薄い)",
    "UNCONFIRMED": "需給の主体は断定できず(板・VWAPが未接続)",
}

def _scout_narrative(assess, flow_inf, ctx, jsf_sig, short_disclosed, m,
                     score_track, engine_cal, posture_cal, is_us):
    """Pure (unit-tested): compose (callJa, narrativeJa) from the assembled
    scout signals. Leads with the MOAT (flow/credit/calibration). Returns
    (None, None) when the assessment is missing."""
    if not isinstance(assess, dict):
        return None, None
    ctx = ctx or {}
    stance = assess.get("stance") or "中立(急がない)"
    score = assess.get("score")
    score_s = f"{'+' if (score or 0) >= 0 else ''}{score}"
    cls = (flow_inf or {}).get("classification") if isinstance(flow_inf, dict) else None
    regime = ctx.get("regime")
    posture = ctx.get("posture")
    rsi = (m or {}).get("rsi14") if isinstance(m, dict) else None

    # ── one-line call: the call + up to 3 dominant context bits ──
    bits = []
    if regime in ("RISK_OFF", "EVENT_WAIT"):
        bits.append(f"地合い{regime}")
    elif posture == "elevated":
        bits.append("金利逆風")
    elif regime == "RISK_ON":
        bits.append("地合いRISK_ON")
    if cls and cls != "UNCONFIRMED" and _FLOW_SHORT.get(cls):
        bits.append(_FLOW_SHORT[cls])
    if isinstance(rsi, (int, float)):
        if rsi <= 30:
            bits.append(f"RSI{rsi}売られすぎ")
        elif rsi >= 70:
            bits.append(f"RSI{rsi}買われすぎ")
    call = _CALL_BY_STANCE.get(stance, stance)
    call_ja = call + (" — " + "・".join(bits[:3]) if bits else "")

    # ── 2-3 sentence story ──
    sents = []
    ground = regime or ("elevated(金利逆風)" if posture == "elevated" else (posture or "中立"))
    sents.append(f"地合いは{ground}、ARGUSの評価は『{stance}』(score {score_s})。")
    if is_us:
        sents.append("米国は信用需給(日証金・空売り開示)が未接続のため、フロー・テクニカル・地合いベースの判断。")
    else:
        extra = []
        if isinstance(jsf_sig, dict) and isinstance(jsf_sig.get("ratio"), (int, float)):
            r = jsf_sig["ratio"]
            rt = str(int(r)) if float(r).is_integer() else str(r)
            # 倍率 = 融資残/貸株残: <1 = 売り長(踏み上げ余地)、高倍率 = 買い長(貸株僅少).
            tag = "・売り長=踏み上げ余地" if r < 1 else ("・買い長(貸株僅少)" if r >= 50 else "")
            extra.append(f"日証金倍率{rt}{tag}")
        if short_disclosed and short_disclosed.get("ratio"):
            extra.append(f"機関空売り{round(short_disclosed['ratio'] * 100, 1)}%")
        story = _FLOW_STORY.get(cls or "UNCONFIRMED")
        sents.append(f"需給の読み: {story}" + (f"({'・'.join(extra)})" if extra else "") + "。")
    # calibration — the thing no LLM has
    cal_bits = []
    if isinstance(score_track, dict) and (score_track.get("n") or 0) >= 5:
        st = score_track
        sub = []
        if st.get("upRate") is not None:
            sub.append(f"{round(st['upRate'] * 100)}%が上昇")
        if st.get("avgRetPct") is not None:
            sub.append(f"平均{'+' if st['avgRetPct'] >= 0 else ''}{st['avgRetPct']}%")
        cal_bits.append(f"このscore水準は過去{st['n']}件中" + ("・".join(sub) if sub else "—"))
    if isinstance(posture_cal, dict) and posture_cal.get("hitRate") is not None and (posture_cal.get("n") or 0) >= 10:
        cal_bits.append(f"この地合い({posture_cal.get('posture')})のエンジン的中率{round(posture_cal['hitRate'] * 100)}%(n={posture_cal['n']})")
    elif isinstance(engine_cal, dict) and engine_cal.get("hitRate") is not None:
        cal_bits.append(f"エンジン全体の的中率{round(engine_cal['hitRate'] * 100)}%(n={engine_cal.get('n')})")
    if cal_bits:
        sents.append("校正: " + "・".join(cal_bits) + "(参考値・蓄積中)。")
    else:
        sents.append("校正: 実績はまだ参考段階(20件未満)。サイズは控えめに。")
    return call_ja, " ".join(sents)

_SCOUT_BUCKETS = (("strong", 1.5), ("lean", 0.5), ("neutral", -0.5), ("avoid", -99))

def _scout_score_bucket(score):
    """Pure (unit-tested): map a scout score to a calibration bucket."""
    if score is None:
        return "neutral"
    for name, lo in _SCOUT_BUCKETS:
        if score >= lo:
            return name
    return "avoid"
