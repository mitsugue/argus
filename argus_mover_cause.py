"""ARGUS V11.3.3 — Mover Cause Engine (pure, deterministic, stdlib-only).

Turns "原因未確認" into a structured attribution ladder for BOTH directions:

    confirmed_cause > probable_catalyst > candidate_catalyst > no_lead_yet
                                                             (not_scoreable)

Discipline (must never be weakened):
- confirmed_cause needs (official disclosure OR multi-source direct news)
  + timing consistency + market confirmation. Nothing else confirms.
- A post-move article can NEVER be the trigger (confirmation/amplifier at best).
- Theme/entity association is a candidate, never a confirmed cause.
- Media single-source is candidate evidence.
- If there is ANY candidate, the answer is candidate_catalyst with
  whyNotConfirmedJa — "unknown" is reserved for a true no-lead.
- no_lead_yet must say what WAS checked and what to check next.
- Upside spikes never become BUY advice here (decision-support text only).

The scanner owns ALL I/O: it collects cached evidence into the `evidence`
dict and calls resolve(). This module only classifies.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "mover-cause-v2"

CAUSE_STATUSES = ["confirmed_cause", "probable_catalyst", "candidate_catalyst",
                  "no_lead_yet", "not_scoreable"]

STATUS_JA = {
    "confirmed_cause": "原因確認",
    "probable_catalyst": "有力材料",
    "candidate_catalyst": "候補",
    "no_lead_yet": "有力候補なし",
    "not_scoreable": "判定不能",
}

CATEGORY_JA = {
    "official_disclosure": "公式開示", "earnings": "決算", "filing": "提出書類",
    "analyst_action": "アナリスト", "direct_news": "直接ニュース",
    "entity_association": "関連企業連想", "theme": "テーマ連想",
    "sector_peer": "同業連動", "macro": "マクロ", "flow_positioning": "需給フロー",
    "technical": "テクニカル", "profit_taking": "利益確定",
    "short_covering": "踏み上げ", "momentum_breakout": "モメンタム",
    "unknown": "不明",
}

_OFFICIAL_CATEGORIES = {"official_disclosure", "earnings", "filing"}

_ANALYST_MARKERS = ("格上げ", "格下げ", "目標株価", "レーティング", "投資判断",
                    "upgrade", "downgrade", "price target", "initiat", "overweight",
                    "underweight")


# ── time helpers ─────────────────────────────────────────────────────────────
def _epoch(v: Any, naive_utc_offset_hours: float = 0.0) -> Optional[float]:
    """Timestamp → epoch. NAIVE timestamps are interpreted as UTC+offset — never
    server-local time (TDnet/yanoshin stamps are JST-naive; a UTC server would
    otherwise read a pre-open 08:30 JST disclosure as 08:30 UTC = after_move)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v > 0 else None
    s = str(v).strip()
    if not s:
        return None
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        pass
    if dt is None:
        try:                                        # RFC-822 (RSS pubDate)
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(s)
        except Exception:
            dt = None
    if dt is None:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:len(fmt) + 2], fmt)
                break
            except Exception:
                continue
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp() - naive_utc_offset_hours * 3600.0
    return dt.timestamp()


def timing_relation(published_at: Any, move_started_at: Any,
                    now_iso: Optional[str] = None,
                    naive_utc_offset_hours: float = 0.0) -> str:
    """before_move / during_move / after_move / unknown.
    during_move = published within 30min after the move started (news breaking
    alongside the move). after_move = later than that — can never be the trigger.
    naive_utc_offset_hours applies to NAIVE published_at stamps (JP feeds = +9)."""
    pub = _epoch(published_at, naive_utc_offset_hours)
    move = _epoch(move_started_at)
    if pub is None or move is None:
        return "unknown"
    if pub <= move:
        # >2.5 days before the move = stale background, treated as unknown timing
        if (move - pub) > 2.5 * 86400:
            return "unknown"
        return "before_move"
    if pub - move <= 1800:
        return "during_move"
    return "after_move"


def _cand_id(category: str, title: str) -> str:
    h = hashlib.md5(f"{category}|{title}".encode("utf-8")).hexdigest()[:10]
    return f"cand-{category}-{h}"


def _mk(category: str, title_ja: str, *, role: str = "background_only",
        source: str = "", source_tier: str = "", source_family: str = "",
        rights_class: str = "", published_at: Any = None, timing: str = "unknown",
        link_type: str = "none", corroboration: str = "none",
        market_confirmed: bool = False, confidence: float = 0.2,
        why_ja: str = "", limitations: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "candidateId": _cand_id(category, title_ja),
        "role": role, "category": category,
        "titleJa": str(title_ja)[:160],
        "source": str(source)[:60], "sourceTier": str(source_tier)[:24],
        "sourceFamily": str(source_family)[:40], "rightsClass": str(rights_class)[:24],
        "publishedAt": (str(published_at)[:32] if published_at else None),
        "timingRelation": timing, "linkType": link_type,
        "corroborationLevel": corroboration, "marketConfirmed": bool(market_confirmed),
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "whyJa": str(why_ja)[:200],
        "limitationsJa": [str(x)[:120] for x in (limitations or [])][:4],
    }


def _sentiment_consistent(sentiment: Any, direction: str) -> Optional[bool]:
    s = str(sentiment or "").lower()
    if s in ("negative", "bad", "neg"):
        return direction == "down"
    if s in ("positive", "good", "pos"):
        return direction == "up"
    return None                                   # unknown sentiment


def _story_tokens(title: str) -> set:
    """Crude story identity: latin words (≥4 chars) + CJK character bigrams
    (no segmenter available — bigrams approximate shared story terms)."""
    import re as _re
    toks = set(t.lower() for t in _re.findall(r"[A-Za-z0-9]{4,}", title or ""))
    for run in _re.findall(r"[぀-ヿ一-鿿]{2,}", title or ""):
        toks |= {run[i:i + 2] for i in range(len(run) - 1)}
    return toks


# ── candidate builders ───────────────────────────────────────────────────────
def build_candidates(mover: Dict[str, Any], evidence: Dict[str, Any],
                     now_iso: str) -> List[Dict[str, Any]]:
    direction = mover.get("direction") or ("down" if (mover.get("changePct") or 0) < 0 else "up")
    chg = mover.get("changePct")
    move_start = mover.get("moveStartedAt")
    big_move = isinstance(chg, (int, float)) and abs(chg) >= 2.0
    # naive timestamps from JP feeds (TDnet/yanoshin) are JST — never server-local
    naive_off = 9.0 if str(mover.get("market") or "JP").upper() == "JP" else 0.0
    out: List[Dict[str, Any]] = []

    # A. official disclosures (TDnet official items + lifecycle events + filings)
    for it in (evidence.get("tdnetItems") or [])[:8]:
        if not isinstance(it, dict):
            continue
        official = bool(it.get("official"))
        timing = timing_relation(it.get("disclosedAt") or it.get("time"), move_start, now_iso,
                                 naive_utc_offset_hours=naive_off)
        material = bool(it.get("material"))
        consistent = _sentiment_consistent(it.get("sentiment"), direction)
        confirmed = official and timing in ("before_move", "during_move") and big_move and consistent is True
        role = ("trigger" if (material and timing in ("before_move", "during_move"))
                else "confirmation" if timing == "after_move" else "background_only")
        conf = 0.75 if confirmed else (0.55 if (official and material and timing != "after_move")
                                       else 0.35 if official else 0.25)
        lims = []
        if timing == "after_move":
            lims.append("値動きより後の開示のため引き金にしない")
        if consistent is None:
            lims.append("開示の方向性(好悪)が未判定")
        out.append(_mk("official_disclosure" if official else "direct_news",
                       f"{it.get('categoryJa') or '開示'}: {it.get('title') or ''}",
                       role=role, source=it.get("provider") or ("TDnet" if official else "TDnet(補助)"),
                       source_tier="official" if official else "aggregator",
                       source_family="tdnet", rights_class="metadata_only",
                       published_at=it.get("disclosedAt") or it.get("time"),
                       timing=timing, link_type="direct_mention",
                       corroboration="official" if official else "single_source",
                       market_confirmed=confirmed, confidence=conf,
                       why_ja="公式開示は事実確認。価格原因の確定には時刻整合+市場反応が必要。",
                       limitations=lims))

    for ev in (evidence.get("officialEvents") or [])[:6]:
        if not isinstance(ev, dict):
            continue
        timing = timing_relation(ev.get("disclosedAt"), move_start, now_iso,
                                 naive_utc_offset_hours=naive_off)
        material = bool(ev.get("material"))
        consistent = _sentiment_consistent(ev.get("sentiment"), direction)
        # NEVER pass the lifecycle record's own causeStatus through as THIS move's
        # market confirmation — it was earned against the disclosure-day reaction,
        # not today's move/direction. Confirmation must be re-proven here.
        confirmed = (timing in ("before_move", "during_move") and material
                     and big_move and consistent is True)
        lims = list(ev.get("missingConfirmations") or [])[:3]
        if timing == "after_move":
            lims.append("値動きより後の開示のため引き金にしない")
        out.append(_mk("official_disclosure",
                       f"{ev.get('categoryJa') or '公式イベント'}: {ev.get('title') or ''}",
                       role="trigger" if (material and timing in ("before_move", "during_move"))
                       else "confirmation",
                       source=ev.get("provider") or "official", source_tier="official",
                       source_family=str(ev.get("source") or "tdnet"),
                       rights_class="metadata_only", published_at=ev.get("disclosedAt"),
                       timing=timing, link_type="direct_mention", corroboration="official",
                       market_confirmed=confirmed,
                       confidence=0.75 if confirmed
                       else (0.6 if (material and timing in ("before_move", "during_move"))
                             else 0.3),
                       why_ja="公式イベントライフサイクルで追跡中。",
                       limitations=lims))

    for f in (evidence.get("filings") or [])[:5]:
        if not isinstance(f, dict):
            continue
        timing = timing_relation(f.get("filingDate") or f.get("submitDateTime"), move_start,
                                 now_iso, naive_utc_offset_hours=naive_off)
        out.append(_mk("filing", f"{f.get('form') or f.get('docTypeCode') or '提出'}: "
                                 f"{f.get('docDescription') or f.get('source') or ''}",
                       role="trigger" if timing in ("before_move", "during_move") else "confirmation",
                       source=str(f.get("source") or "filing"), source_tier="official",
                       source_family="edinet_sec", rights_class="metadata_only",
                       published_at=f.get("filingDate") or f.get("submitDateTime"),
                       timing=timing, link_type="direct_mention", corroboration="official",
                       confidence=0.45 if timing != "after_move" else 0.3,
                       why_ja="公式提出書類。内容の好悪と価格因果は未確定。"))

    # B. earnings proximity (a real, honest vulnerability/candidate)
    earn = evidence.get("earnings") or {}
    dte = earn.get("daysToEarnings")
    if isinstance(dte, (int, float)) and 0 <= dte <= 5 and not earn.get("resultReleased"):
        out.append(_mk("earnings", f"決算発表まで{int(dte)}日(結果は未発表)",
                       role="vulnerability", source="calendar", source_tier="official",
                       corroboration="official", confidence=0.4,
                       why_ja="決算前のイベントリスク回避売買が値動きを増幅しやすい。"
                              "未発表の決算は原因にしない。",
                       limitations=["未発表の決算結果を原因と断定しない"]))

    # C. direct company news (Finnhub US / Google News JP)
    news = list(evidence.get("companyNews") or []) + list(evidence.get("jpNews") or [])
    fresh = []
    for n in news[:12]:
        if not isinstance(n, dict):
            continue
        timing = timing_relation(n.get("publishedAt") or n.get("datetime"), move_start, now_iso,
                                 naive_utc_offset_hours=naive_off)
        title = str(n.get("headline") or n.get("titleJa") or n.get("title") or "")
        if not title:
            continue
        fresh.append((n, timing, title))

    def _is_multi(n0, t0, title0):
        """multi_source = the SAME STORY reported before/during the move by ≥2
        distinct NAMED publishers (story identity via shared significant tokens).
        Two unrelated articles about the company are NOT corroboration."""
        if t0 not in ("before_move", "during_move"):
            return False
        pub0 = str(n0.get("publisher") or n0.get("source") or "").strip()
        toks0 = _story_tokens(title0)
        if not pub0 or not toks0:
            return False
        for n1, t1, title1 in fresh:
            if n1 is n0 or t1 not in ("before_move", "during_move"):
                continue
            pub1 = str(n1.get("publisher") or n1.get("source") or "").strip()
            if not pub1 or pub1 == pub0:
                continue
            if toks0 & _story_tokens(title1):
                return True
        return False

    for n, timing, title in fresh[:6]:
        is_analyst = any(m in title.lower() for m in _ANALYST_MARKERS)
        corro = "multi_source" if _is_multi(n, timing, title) else "single_source"
        consistent = _sentiment_consistent(n.get("sentiment"), direction)
        confirmed = corro == "multi_source" and timing in ("before_move", "during_move") \
            and big_move and consistent is True
        conf = 0.6 if confirmed else (0.45 if corro == "multi_source"
                                      else 0.35 if timing in ("before_move", "during_move") else 0.25)
        lims = ["単一ソースは候補止まり(裏取りが必要)"] if corro == "single_source" else []
        if timing == "after_move":
            lims.append("値動きより後の記事のため引き金にしない")
        out.append(_mk("analyst_action" if is_analyst else "direct_news", title,
                       role=("trigger" if timing in ("before_move", "during_move") else "amplifier"),
                       source=str(n.get("publisher") or n.get("source") or "media"),
                       source_tier=str(n.get("tier") or "media"),
                       source_family="company_news", rights_class="metadata_only",
                       published_at=n.get("publishedAt") or n.get("datetime"),
                       timing=timing, link_type="direct_mention", corroboration=corro,
                       market_confirmed=confirmed, confidence=conf,
                       why_ja="銘柄を直接報じるニュース。", limitations=lims))

    # D. C.A.O.S. association lead (entity/theme — candidate by definition)
    lead = evidence.get("caosLead")
    if isinstance(lead, dict) and lead.get("titleJa"):
        via = str(lead.get("via") or "theme")
        out.append(_mk("entity_association" if via in ("entity", "entity_profile", "name")
                       else "theme", str(lead.get("titleJa")),
                       role="vulnerability", source="C.A.O.S.", source_tier="association",
                       source_family="caos", rights_class="metadata_only",
                       link_type="entity_profile" if via.startswith("entity") else "theme",
                       corroboration=str(lead.get("corroboration") or "single_source"),
                       confidence=0.3,
                       why_ja=str(lead.get("relationJa") or "関連企業/テーマの連想リード。"),
                       limitations=["連想は原因ではない(候補どまり)"]))

    # E. sector/theme peers moving together
    peers = evidence.get("peers") or {}
    total = peers.get("peersTotal") or 0
    same = peers.get("peersSameDirection") or 0
    if total >= 3 and same >= 2:
        frac = same / max(total, 1)
        strong = frac >= 0.6
        out.append(_mk("sector_peer",
                       f"同業/テーマ{total}銘柄中{same}銘柄が同方向"
                       f"({peers.get('theme') or 'セクター'})",
                       role="propagation", source="peer_basket", source_tier="derived",
                       corroboration="market_confirmed" if strong else "none",
                       market_confirmed=strong, link_type="theme",
                       confidence=0.5 if strong else 0.3,
                       why_ja="個別材料ではなくセクター/テーマ全体の動きが主因の可能性。"))

    # F. macro events (released today with consistent direction)
    for m in (evidence.get("macroEvents") or [])[:3]:
        if not isinstance(m, dict):
            continue
        out.append(_mk("macro", f"{m.get('eventCode') or 'マクロ'}: {m.get('title') or ''}",
                       role="propagation", source=str(m.get("source") or "macro"),
                       source_tier="official", corroboration="official",
                       market_confirmed=bool(m.get("marketConsistent")),
                       confidence=0.45 if m.get("marketConsistent") else 0.3,
                       why_ja=str(m.get("whyJa") or "本日のマクロイベントが地合いを動かした可能性。")))

    # G. flow / positioning
    flow = evidence.get("flow") or {}
    bnr = flow.get("bigNetRatio")
    if isinstance(bnr, (int, float)) and abs(bnr) >= 0.12:
        selling = bnr < 0
        cat = "flow_positioning"
        if direction == "up" and not selling and (evidence.get("margin") or {}).get("shortHeavy"):
            cat = "short_covering"
        if (selling and direction == "down") or ((not selling) and direction == "up"):
            out.append(_mk(cat, f"大口フロー{'売り' if selling else '買い'}優勢"
                                f"(bigNetRatio {bnr:+.2f})",
                           role="amplifier", source="moomoo-flow", source_tier="derived",
                           corroboration="market_confirmed", market_confirmed=True,
                           confidence=0.35,
                           why_ja="実測フローは増幅要因。主体の特定はできない(断定しない)。",
                           limitations=["フローから主体は特定できない"]))

    # H. technical context (prior run-up → profit taking / breakout)
    tech = evidence.get("technical") or {}
    runup = tech.get("priorRunupPct")
    if isinstance(runup, (int, float)):
        if direction == "down" and runup >= 12:
            out.append(_mk("profit_taking", f"直近{runup:+.0f}%上昇後の利益確定売りの可能性",
                           role="vulnerability", source="price_history", source_tier="derived",
                           confidence=0.35,
                           why_ja="大幅上昇後の下げは材料が無くても起こる(ポジション整理)。"))
        elif direction == "up" and runup >= 12:
            out.append(_mk("momentum_breakout", f"直近{runup:+.0f}%上昇のモメンタム継続",
                           role="background_only", source="price_history", source_tier="derived",
                           confidence=0.25,
                           why_ja="モメンタム自体は原因ではなく状態。高値追いの根拠にしない。",
                           limitations=["急騰の追随買い推奨ではない"]))

    # deterministic order: confidence desc, then stable id
    out.sort(key=lambda c: (-c["confidence"], c["candidateId"]))
    return out[:12]


# ── ladder resolution ────────────────────────────────────────────────────────
def _status_from(candidates: List[Dict[str, Any]]):
    """Returns (status, winning_candidate) — the record's bestLead/why-not text
    must come from the candidate that EARNED the status, not merely the
    highest-confidence one (they can differ)."""
    for c in candidates:
        if (c["category"] in _OFFICIAL_CATEGORIES and c["corroborationLevel"] == "official"
                and c["timingRelation"] in ("before_move", "during_move")
                and c["marketConfirmed"]):
            return "confirmed_cause", c
        if (c["corroborationLevel"] == "multi_source" and c["linkType"] == "direct_mention"
                and c["timingRelation"] in ("before_move", "during_move")
                and c["marketConfirmed"]):
            return "confirmed_cause", c
    for c in candidates:
        if c["category"] in _OFFICIAL_CATEGORIES and c["confidence"] >= 0.45:
            return "probable_catalyst", c                    # official fact, causality unclear
        if (c["corroborationLevel"] == "multi_source" and c["confidence"] >= 0.45):
            return "probable_catalyst", c
        if (c["category"] == "direct_news" and c["timingRelation"] in ("before_move", "during_move")
                and c["confidence"] >= 0.35 and c["sourceTier"] in ("wire", "official")):
            return "probable_catalyst", c
        if c["category"] == "sector_peer" and c["marketConfirmed"]:
            return "probable_catalyst", c
        if c["category"] == "macro" and c["marketConfirmed"]:
            return "probable_catalyst", c
    for c in candidates:
        if c["confidence"] >= 0.2 and c["role"] != "background_only":
            return "candidate_catalyst", c
        if c["category"] in ("direct_news", "analyst_action", "entity_association", "theme",
                             "profit_taking", "short_covering", "flow_positioning"):
            return "candidate_catalyst", c
    return "no_lead_yet", None


def _why_not_confirmed(status: str, top: Optional[Dict[str, Any]]) -> str:
    if status == "confirmed_cause":
        return ""
    if status == "no_lead_yet":
        return "確認済みの情報源に該当する材料が見つかっていない(=安全の証明ではない)。"
    if not top:
        return "候補の裏取りができていない。"
    parts = []
    if top["corroborationLevel"] == "single_source":
        parts.append("単一ソースのため裏取りが必要")
    if top["timingRelation"] == "after_move":
        parts.append("値動きより後の情報のため引き金と断定できない")
    if top["timingRelation"] == "unknown":
        parts.append("発表時刻と値動きの時刻整合が未確認")
    if not top["marketConfirmed"]:
        parts.append("市場反応との整合が未確認")
    if top["category"] in ("entity_association", "theme"):
        parts.append("連想リンクであり直接材料ではない")
    return "。".join(parts[:3]) + "。" if parts else "公式確認が揃っていない。"


def _next_checks(coverage: Dict[str, Any], candidates: List[Dict[str, Any]],
                 market: str) -> List[str]:
    checks: List[str] = []
    if not coverage.get("tdnetChecked") and market == "JP":
        checks.append("TDnet公式開示を確認")
    if not coverage.get("companyNewsChecked") and market == "US":
        checks.append("企業ニュース(Finnhub)を確認")
    if not coverage.get("jpNewsChecked") and market == "JP":
        checks.append("日本語ニュース(Google News)を確認")
    if not coverage.get("flowChecked"):
        checks.append("出来高・大口フローを確認")
    if not coverage.get("sectorPeerChecked"):
        checks.append("同業銘柄の値動きを確認")
    if any(c["timingRelation"] == "unknown" for c in candidates[:3]):
        checks.append("候補材料の発表時刻と値動き開始時刻の整合を確認")
    if any(c["corroborationLevel"] == "single_source" for c in candidates[:3]):
        checks.append("別ソースでの裏取り(2社目の報道/公式開示)を確認")
    checks.append("次の公式開示・決算・適時開示を待つ")
    return checks[:4]


def resolve(mover: Dict[str, Any], evidence: Dict[str, Any],
            now_iso: str) -> Dict[str, Any]:
    """Build the full mover-cause record. Pure — the scanner supplies evidence."""
    symbol = str(mover.get("symbol") or "").upper()
    market = str(mover.get("market") or "JP").upper()
    chg = mover.get("changePct")
    direction = mover.get("direction") or ("down" if isinstance(chg, (int, float)) and chg < 0 else "up")
    day = (str(mover.get("asOf") or now_iso)[:10]).replace("-", "")
    coverage = {k: bool((evidence.get("coverage") or {}).get(k)) for k in (
        "tdnetChecked", "officialEventsChecked", "edinetSecChecked", "companyNewsChecked",
        "jpNewsChecked", "caosChecked", "sectorPeerChecked", "macroChecked",
        "flowChecked", "technicalChecked")}

    if not isinstance(chg, (int, float)):
        status, candidates, winner = "not_scoreable", [], None
    else:
        candidates = build_candidates({**mover, "direction": direction}, evidence, now_iso)
        status, winner = _status_from(candidates)
        # the status-earning candidate leads the record — surface it first
        if winner is not None and candidates and candidates[0] is not winner:
            candidates = [winner] + [c for c in candidates if c is not winner]

    top = winner or (candidates[0] if candidates else None)
    status_ja = STATUS_JA[status]
    best = ""
    if top and status != "no_lead_yet":
        best = f"{CATEGORY_JA.get(top['category'], top['category'])}: {top['titleJa']}"
    checked_ja = "/".join(l for l, k in (
        ("TDnet", "tdnetChecked"), ("公式イベント", "officialEventsChecked"),
        ("ニュース", "companyNewsChecked"), ("日本語ニュース", "jpNewsChecked"),
        ("C.A.O.S.", "caosChecked"), ("同業", "sectorPeerChecked"),
        ("マクロ", "macroChecked"), ("フロー", "flowChecked")) if coverage.get(k))

    conf = round(top["confidence"], 2) if top else 0.0
    unknown = {"confirmed_cause": 0.1, "probable_catalyst": 0.35,
               "candidate_catalyst": 0.6, "no_lead_yet": 0.9,
               "not_scoreable": 1.0}[status]

    missing: List[str] = []
    if status != "confirmed_cause":
        if not (top and top["marketConfirmed"]):
            missing.append("市場反応との整合")
        if not (top and top["corroborationLevel"] in ("official", "multi_source")):
            missing.append("公式開示または複数ソースの裏取り")
        if top and top["timingRelation"] not in ("before_move", "during_move"):
            missing.append("時刻整合(材料が値動きより先)")

    impact = ""
    if isinstance(chg, (int, float)):
        if direction == "down":
            impact = ("原因確定前の狼狽売りはしない。" if status in ("candidate_catalyst", "no_lead_yet")
                      else "材料の内容を確認してから保有判断を更新する。")
        else:
            impact = "急騰の追随買いは高値掴みリスク。材料候補があっても高値追い注意。" \
                if abs(chg) >= 8 else "上昇理由が確認できるまで新規追加は慎重に。"

    return {
        "schemaVersion": SCHEMA_VERSION,
        "moverCauseId": f"mc-{market}-{symbol}-{day}",
        "symbol": symbol, "market": market, "direction": direction,
        "changePct": (round(float(chg), 2) if isinstance(chg, (int, float)) else None),
        "name": str(mover.get("name") or "")[:60],
        "asOf": now_iso,
        "causeStatus": status, "causeStatusJa": status_ja,
        "bestLeadJa": best[:200],
        "confidence": conf,
        "unknownShare": unknown,
        "whyNotConfirmedJa": _why_not_confirmed(status, top),
        "causeCandidates": candidates,
        "evidenceCoverage": coverage,
        "checkedJa": checked_ja,
        "missingConfirmations": missing[:4],
        "nextChecksJa": _next_checks(coverage, candidates, market),
        "impactCommentJa": impact,
        "explanationJa": None, "explanationGeneratedAt": None,
        "recordRefs": {"eventCardId": None, "evidencePackId": None,
                       "officialEventId": (evidence.get("officialEvents") or [{}])[0].get("officialEventId")
                       if evidence.get("officialEvents") else None,
                       "caosAuditIds": []},
    }


def compact(record: Dict[str, Any]) -> Dict[str, Any]:
    """Small projection embedded into downside incidents / mover rows."""
    return {
        "causeStatus": record.get("causeStatus"),
        "causeStatusJa": record.get("causeStatusJa"),
        "bestLeadJa": record.get("bestLeadJa"),
        "whyNotConfirmedJa": record.get("whyNotConfirmedJa"),
        "checkedJa": record.get("checkedJa"),
        "nextChecksJa": (record.get("nextChecksJa") or [])[:2],
        "impactCommentJa": record.get("impactCommentJa"),
        "confidence": record.get("confidence"),
        "topCandidates": [
            {k: c.get(k) for k in ("titleJa", "category", "timingRelation",
                                   "corroborationLevel", "confidence", "source")}
            for c in (record.get("causeCandidates") or [])[:3]
        ],
    }


def reason_suffix_ja(record: Dict[str, Any]) -> str:
    """The sentence appended to an incident's reasonJa — never a bare 原因未確認."""
    status = record.get("causeStatus")
    best = record.get("bestLeadJa") or ""
    if status == "confirmed_cause":
        return f"原因確認: {best}"
    if status == "probable_catalyst":
        return f"原因確定なし。有力材料: {best}({record.get('whyNotConfirmedJa') or ''})"
    if status == "candidate_catalyst":
        return f"原因確定なし。ただし有力候補: {best}({record.get('whyNotConfirmedJa') or ''})"
    if status == "not_scoreable":
        return "価格データ不足のため原因判定不能(データ復旧後に再判定)。"
    checked = record.get("checkedJa") or "情報源"
    nxt = "・".join((record.get("nextChecksJa") or [])[:2])
    return f"現時点で有力候補なし。確認済み: {checked}。次に確認: {nxt}"
