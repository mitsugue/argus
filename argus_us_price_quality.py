"""The quality of the US prices the service holds, apart from any one route (2026-10-20).

The owner asked that the moomoo bridge's state and the quality of the US
prices be shown apart: a silent bridge is a route state, while the service
question is whether every target symbol has a price whose own source time is
recent enough, whichever route delivered it. A configured provider key, a
heartbeat or a close-of-session value is never shown as a normal receipt, and
when the target list or the prices cannot be read the lamp says 未確認.

Counts only: no symbol, price or account detail leaves this module.
Pure functions: no clock, no store, no network.
"""
from typing import Any, Dict, Iterable, Mapping, Optional

#: Same bound as the decision-usable quote contract (a source time within 20 minutes).
LIVE_MAX_AGE_SEC = 20 * 60


def _route(row: Mapping[str, Any]) -> str:
    if row.get('transportAgeSec') is not None:
        return 'moomoo'
    source = str(row.get('source') or row.get('provider') or '').lower()
    if 'twelve' in source:
        return 'twelvedata'
    return 'other'


def _priced(row: Optional[Mapping[str, Any]]) -> bool:
    if not isinstance(row, Mapping):
        return False
    if str(row.get('status') or '').lower() in ('mock', 'unavailable', 'offline', 'error'):
        return False
    price = row.get('price')
    return isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0


def _fresh(row: Mapping[str, Any]) -> bool:
    age = row.get('ageSec')
    return (row.get('sourceTimeStatus') == 'PRESENT' and not row.get('timestampInversion')
            and isinstance(age, int) and 0 <= age <= LIVE_MAX_AGE_SEC)


def assess(targets: Optional[Iterable[str]], rows: Mapping[str, Any], *, session_open: bool) -> Dict[str, Any]:
    """{'status', 'detailJa', 'counts'} for the 米国株価格 lamp.

    `targets` is the list the service keeps priced (None when it cannot be
    read); `rows` maps each target to its cached quote row (re-aged by its own
    source time) or None."""
    if targets is None:
        return {'status': 'warning', 'detailJa': '未確認 — 対象の一覧をまだ読めない', 'counts': None}
    symbols = list(dict.fromkeys(targets))
    total = len(symbols)
    if not total:
        return {'status': 'warning', 'detailJa': '未確認 — 対象が0銘柄', 'counts': {'targets': 0}}
    priced = [s for s in symbols if _priced(rows.get(s))]
    fresh = [s for s in priced if _fresh(rows[s])]
    routes = {'moomoo': 0, 'twelvedata': 0, 'other': 0}
    for s in priced:
        routes[_route(rows[s])] += 1
    counts = {'targets': total, 'priced': len(priced), 'fresh': len(fresh), 'routes': routes}
    route_ja = '経路 moomoo {moomoo} · Twelve Data {twelvedata}'.format(**routes) \
        + (f' · その他 {routes["other"]}' if routes['other'] else '')
    if not session_open:
        return {'status': 'off', 'counts': counts,
                'detailJa': f'市場時間外 · 価格あり {len(priced)}/{total}銘柄(閉場時の値で、実時間の受信ではない) · {route_ja}'}
    if not priced:
        # Amber, not red: a red price lamp is read elsewhere as a hard degradation
        # of the analysis, and this change is a display and diagnosis only.
        return {'status': 'warning', 'counts': counts,
                'detailJa': f'市場時間中・価格なし 0/{total}銘柄 · どの経路からも届いていない'}
    if len(fresh) == total:
        return {'status': 'ok', 'counts': counts,
                'detailJa': f'{total}/{total}銘柄の価格時刻が20分以内 · {route_ja}'}
    missing, stale = total - len(priced), len(priced) - len(fresh)
    parts = [f'価格時刻20分以内 {len(fresh)}/{total}銘柄']
    if stale:
        parts.append(f'古い・時刻不明 {stale}')
    if missing:
        parts.append(f'価格なし {missing}')
    return {'status': 'warning', 'counts': counts, 'detailJa': ' · '.join(parts) + f' · {route_ja}'}
