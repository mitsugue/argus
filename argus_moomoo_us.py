"""米国株の参照データを moomoo のブリッジから受け取るための純粋な規則(2026-10-22)。

オーナーの方針: 米国株のデータは moomoo が主役。Twelve Data は、ここにある
日足が無い時の最後の手段に下げる。ここには入出力も時計も無く、受け取った行の
検証・保存済みの足との突き合わせ・ブリッジへ頼む銘柄の計画だけを置く。

- 日足は確定足だけ(取引所の暦で終わった取引日まで)。未確定の足は受け取らない。
- 足の値は moomoo の前方調整(分割と配当)。差分の受け取りで重なった日の値が
  変わっていたら(配当で過去が調整し直された等)、混ぜずに全期間の取り直しを頼む。
- 欠けた値を推測で埋めない。
"""
from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DAILY_SCHEMA = "moomoo-us-daily-v1"
ADJUSTMENT = "qfq"                 # moomoo AuType.QFQ(前方調整)
MAX_BARS = 2600                    # 約10年分(Twelve Data の取得量 2520 本と同等)
FULL_HISTORY_DAYS = 3700           # 全期間の取り直しで頼む暦日数(約10年)
OVERLAP_DAYS = 14                  # 差分で頼む時に重ねる暦日数
OVERLAP_RELATIVE_TOLERANCE = 1e-4  # 重なった日の終値の許容差(相対)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _finite(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _exact_date(value: Any) -> Optional[date]:
    text = str(value or "")[:10]
    if not _DATE_RE.match(text):
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def normalize_daily_rows(rows: Iterable[Any], *, end: date,
                         is_trading_day=None) -> Tuple[List[List[Any]], int]:
    """ブリッジの [[日付, 始値, 高値, 安値, 終値, 出来高], ...] を検証して昇順で返す。

    end より後の日付(未確定の足)・休場日・壊れた値は捨て、捨てた数を返す。
    同じ日付が二度来た行は、どちらも信用せず両方捨てる。"""
    kept: Dict[str, List[Any]] = {}
    duplicated = set()
    rejected = 0
    for raw in rows or []:
        if not isinstance(raw, (list, tuple)) or len(raw) < 5:
            rejected += 1
            continue
        day = _exact_date(raw[0])
        if day is None or day > end or (is_trading_day and not is_trading_day(day)):
            rejected += 1
            continue
        o, h, l, c = (_finite(raw[1]), _finite(raw[2]), _finite(raw[3]), _finite(raw[4]))
        volume = _finite(raw[5]) if len(raw) > 5 else None
        if c is None or c <= 0 or any(v is not None and v <= 0 for v in (o, h, l)):
            rejected += 1
            continue
        if h is not None and l is not None and h < l:
            rejected += 1
            continue
        if volume is not None and volume < 0:
            rejected += 1
            continue
        key = day.isoformat()
        if key in kept:
            duplicated.add(key)
            continue
        kept[key] = [key, o, h, l, c, int(volume) if volume is not None else None]
    for key in duplicated:
        kept.pop(key, None)
        rejected += 2
    return [kept[key] for key in sorted(kept)], rejected


def merge_daily_bars(stored: Sequence[Sequence[Any]], incoming: Sequence[Sequence[Any]], *,
                     full: bool) -> Tuple[List[List[Any]], str]:
    """保存済みの足と受け取った足を合わせる。

    戻り値の状態: replaced(全期間で置き換え) / appended(新しい日を足した) /
    unchanged(新しい日なし) / overlap_mismatch(重なった日の値が違う) /
    no_overlap(重なりが無く続きか確かめられない) / empty(受け取りが空)。
    後ろの二つと overlap_mismatch では保存済みの足をそのまま返す。"""
    incoming = [list(row) for row in incoming]
    if not incoming:
        return [list(row) for row in stored], "empty"
    if full or not stored:
        return incoming[-MAX_BARS:], "replaced"
    by_date = {row[0]: row for row in stored}
    overlap = [row for row in incoming if row[0] in by_date]
    if not overlap:
        return [list(row) for row in stored], "no_overlap"
    for row in overlap:
        old_close = by_date[row[0]][4]
        if not old_close or abs(float(row[4]) - float(old_close)) / abs(float(old_close)) \
                > OVERLAP_RELATIVE_TOLERANCE:
            return [list(r) for r in stored], "overlap_mismatch"
    last = stored[-1][0]
    newer = [row for row in incoming if row[0] > last]
    if not newer:
        return [list(row) for row in stored], "unchanged"
    return ([list(row) for row in stored] + newer)[-MAX_BARS:], "appended"


def plan_daily_requests(symbols: Sequence[str], index: Mapping[str, Mapping[str, Any]], *,
                        end: date) -> List[Dict[str, Any]]:
    """ブリッジへ頼む日足の一覧。end までそろっている銘柄は頼まない。"""
    out = []
    seen = set()
    for raw in symbols:
        sym = str(raw or "").strip().upper()
        if not SYMBOL_RE.match(sym) or sym in seen:
            continue
        seen.add(sym)
        entry = index.get(sym) or {}
        last = _exact_date(entry.get("lastDate"))
        full = (not entry or not entry.get("fullHistory") or entry.get("needsRefill")
                or last is None)
        if not full and last >= end:
            continue
        start = (end - timedelta(days=FULL_HISTORY_DAYS)) if full else \
            (last - timedelta(days=OVERLAP_DAYS))
        out.append({"code": f"US.{sym}", "symbol": sym, "start": start.isoformat(),
                    "end": end.isoformat(), "full": bool(full)})
    return out


def index_entry(bars: Sequence[Sequence[Any]], *, full_history: bool, needs_refill: bool,
                received_at: str) -> Dict[str, Any]:
    return {
        "firstDate": bars[0][0] if bars else None,
        "lastDate": bars[-1][0] if bars else None,
        "bars": len(bars),
        "fullHistory": bool(full_history),
        "needsRefill": bool(needs_refill),
        "receivedAt": received_at,
        "adjust": ADJUSTMENT,
    }


def history_newest_first(bars: Sequence[Sequence[Any]], limit: Optional[int] = None) -> Dict[str, list]:
    """Twelve Data の履歴と同じ形(新しい順)。値が欠けた所は None のまま。"""
    rows = list(bars)[::-1]
    if limit is not None:
        rows = rows[:limit]
    return {
        "opens": [row[1] for row in rows],
        "closes": [row[4] for row in rows],
        "highs": [row[2] for row in rows],
        "lows": [row[3] for row in rows],
        "volumes": [int(row[5] or 0) for row in rows],
        "dates": [row[0] for row in rows],
        "adjusted": [True for _ in rows],
    }
