"""既存保存から共有の固定銘柄の決算予定だけを日付の予定へ投影する。"""
from datetime import datetime,date,time,timedelta
from zoneinfo import ZoneInfo
from collections.abc import Mapping


def scheduled_events(items, *, shared_symbols, now, horizon_days=45):
    if now.tzinfo is None:
        raise ValueError('timezone_required')
    events, gaps = [], []
    for market,symbol,name in shared_symbols:
        if market not in ('JP','US'):
            continue
        raw=items.get(f'{market}:{symbol}') or {}
        if not isinstance(raw,Mapping):
            continue
        earnings=raw.get('earnings') or {}
        if not isinstance(earnings,Mapping):
            continue
        schedule=earnings.get('next') or {}
        if not isinstance(schedule,Mapping):
            continue
        if earnings.get('market')!=market or earnings.get('symbol')!=symbol:
            continue
        certainty=schedule.get('certainty')
        tz_name='Asia/Tokyo' if market=='JP' else 'America/New_York'
        if certainty not in ('COMPANY_SCHEDULE','PROVIDER_ESTIMATE') or schedule.get('timezone')!=tz_name:
            continue
        if raw.get('scheduleStatus') in ('NO_SCHEDULE','CONFLICT'):
            continue
        try:
            first=date.fromisoformat(schedule['from']);last=date.fromisoformat(schedule['to'])
            if first.isoformat()!=schedule['from'] or last.isoformat()!=schedule['to']:
                continue
            today=now.astimezone(ZoneInfo(tz_name)).date()
            receipt_text=schedule.get('fetchedAt') or earnings.get('fetchedAt')
            if not isinstance(receipt_text,str):
                continue
            receipt=datetime.fromisoformat(receipt_text.replace('Z','+00:00'))
            if receipt.tzinfo is None or receipt>now:
                continue
            if first>last or (last-first).days>7 or last<today or first>today+timedelta(days=horizon_days):
                continue
            if certainty=='PROVIDER_ESTIMATE' and now-receipt>timedelta(days=7):
                gaps.append('corporate_earnings_estimate_stale');continue
            if certainty=='COMPANY_SCHEDULE':
                published=date.fromisoformat(schedule['publishedDate'])
                if (market!='JP' or first!=last or schedule.get('source')!='J-Quants 決算発表予定日'
                        or published>receipt.astimezone(ZoneInfo(tz_name)).date()):
                    continue
            elif earnings.get('source')!='Yahoo Finance':
                continue
            start=datetime.combine(first,time.min,ZoneInfo(tz_name))
            end=datetime.combine(last,time(23,59,59),ZoneInfo(tz_name))
        except (ValueError,KeyError,TypeError):
            continue
        events.append({'eventId':f'corporate-earnings-{market}-{symbol}-{first}-{last}',
            'kind':'CORPORATE_EARNINGS','market':market,'sourceTimezone':tz_name,
            'sourceFromDate':first.isoformat(),'sourceToDate':last.isoformat(),
            'rangeEndAt':end.isoformat(),'at':start.isoformat(),'date':first.isoformat(),'dateOnly':True,
            'daysUntil':max(0,(first-today).days),'titleJa':name+' 決算'+('予定' if certainty=='COMPANY_SCHEDULE' else '（推定）'),
            'importance':'medium','whatJa':'会社公表の発表予定日。' if certainty=='COMPANY_SCHEDULE' else '提供元が見込む発表日。',
            'soWhatJa':'業績・会社予想と、発表後の同業株・指数の反応を確認。',
            'watchJa':'実績・会社予想・市場予想との差。',
            'source':'J-Quants 決算発表予定日' if certainty=='COMPANY_SCHEDULE' else 'Yahoo Finance',
            'certainty':certainty,'receivedAt':receipt.isoformat(),'actionAuthority':False})
    return events,sorted(set(gaps))
