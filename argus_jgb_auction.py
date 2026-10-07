"""Bounded official result parser; observations only, no demand/price forecast."""
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from html.parser import HTMLParser
import re
import unicodedata
from urllib.parse import urljoin

ROOT = 'https://www.mof.go.jp/jgbs/auction/calendar/'
TENORS = (10, 20, 30, 40)
ARCHIVE_URL = 'https://www.mof.go.jp/jgbs/reference/appendix/jgb_historical_data.xls'


def parse_archive(raw, *, acquired_at):
    """Official selected fields, received now; not a historical publication vintage.

    Monthly calendars cover the most recent two months. The archive only fills
    older sessions, so rounded archive amounts cannot revise native results.
    Other debt types and noncompetitive accepted amounts are not substituted.
    """
    import math
    import xlrd
    from zoneinfo import ZoneInfo
    from argus_jp_fiscal_monitor import instant, digest
    today = instant(acquired_at).astimezone(ZoneInfo('Asia/Tokyo')).date()
    prior_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    try:
        first = today.replace(year=today.year-10)
    except ValueError:
        first = today.replace(year=today.year-10,day=28)
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1_000_000:
        raise ValueError('auction_archive_size')
    book = xlrd.open_workbook(file_contents=raw, on_demand=True)
    rows = []
    try:
        for tenor in TENORS:
            sheet = book.sheet_by_name(f'{tenor}年債')
            if not 6 <= sheet.nrows <= 1000 or not 10 <= sheet.ncols <= 20:
                raise ValueError('auction_archive_dimensions')
            headings = sheet.row_values(2)
            def column(label):
                found = [i for i, value in enumerate(headings) if _norm(str(value)) == label]
                if len(found) != 1: raise ValueError('auction_archive_header')
                return found[0]
            fields = {label:column(label) for label in
                ('回号','入札日','応募額','落札・割当額','最高利回')}
            if tenor != 40: fields['平均利回'] = column('平均利回')
            for label in ('応募額','落札・割当額'):
                if _norm(str(sheet.cell_value(4,fields[label]))) != '(億円)(100millionyen)':
                    raise ValueError('auction_archive_amount_unit')
            for label in ('最高利回','平均利回'):
                if label in fields and _norm(str(sheet.cell_value(4,fields[label]))) != '(%)':
                    raise ValueError('auction_archive_yield_unit')
            seen = set(); previous = None
            def number(r, label):
                value = sheet.cell_value(r, fields[label])
                if isinstance(value, bool) or not isinstance(value, (float,int)) or not math.isfinite(value):
                    raise ValueError('auction_archive_number')
                return Decimal(str(value))
            for r in range(5,sheet.nrows):
                serial = number(r,'入札日')
                if serial != serial.to_integral(): raise ValueError('auction_archive_session')
                session = xlrd.xldate_as_datetime(float(serial), book.datemode).date()
                if session > today or session in seen or (previous is not None and session <= previous):
                    raise ValueError('auction_archive_date_order')
                previous = session; seen.add(session)
                if not first <= session < prior_month: continue
                issue = number(r,'回号')
                bids = number(r,'応募額') * 10**8
                accepted = number(r,'落札・割当額') * 10**8
                high = number(r,'最高利回')
                average = number(r,'平均利回') if tenor != 40 else None
                if issue != issue.to_integral() or not 0 < issue < 10000:
                    raise ValueError('auction_archive_issue')
                if bids != bids.to_integral() or accepted != accepted.to_integral() or not 0 < accepted <= bids <= 10**15:
                    raise ValueError('auction_archive_amount')
                if not -5 < high < 30 or (average is not None and not -5 < average <= high):
                    raise ValueError('auction_archive_yield')
                row = {'schemaVersion':'jp-jgb-auction-observation-v1',
                    'sessionDate':session.isoformat(),'tenorYears':tenor,'issueNumber':int(issue),
                    'auctionMethod':'PRICE_COMPETITIVE' if tenor != 40 else 'UNIFORM_YIELD',
                    'competitiveBidAmountJpy':int(bids),'competitiveAcceptedAmountJpy':int(accepted),
                    'bidToCover':float(bids/accepted),'highestAcceptedYieldPct':float(high),
                    'averageAcceptedYieldPct':float(average) if average is not None else None,
                    'yieldTailBp':float((high-average)*100) if average is not None else None,
                    'publishedDate':None,'publishedAt':None,'knownAt':acquired_at,'acquiredAt':acquired_at,
                    'sourceUrl':ARCHIVE_URL,'sourceHash':sha256(raw).hexdigest(),
                    'sourceSheet':sheet.name,'sourceRow':r+1,'amountUnit':'100_MILLION_JPY',
                    'sourceKind':'OFFICIAL_HISTORICAL_COMPILATION',
                    'availabilityBasis':'ACTUAL_RECEIPT','historicalVintageVerified':False,
                    'acquisitionStatus':'AVAILABLE','actionAuthority':False,'predictivePerformance':'UNVALIDATED'}
                row['id']='jgb-auction-'+digest({k:v for k,v in row.items()
                    if k not in ('knownAt','acquiredAt','sourceHash','sourceRow')})
                rows.append(row)
            if not any(row['tenorYears']==tenor for row in rows):
                raise ValueError('auction_archive_tenor_empty')
    finally:
        book.release_resources()
    return sorted(rows,key=lambda row:(row['sessionDate'],row['tenorYears']))


def _norm(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


class _Document(HTMLParser):
    def __init__(self, raw):
        super().__init__()
        self.rows = []; self.text = []; self.stack = []
        self.cell = None; self.hidden = 0
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= 256_000:
            raise ValueError('auction_source_size')
        self.feed(raw.decode('utf-8-sig'))

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'): self.hidden += 1
        if self.hidden: return
        if tag == 'tr': self.stack.append([])
        if tag in ('td', 'th') and self.stack:
            self.cell = {'text': [], 'links': []}
            self.stack[-1].append(self.cell)
        if tag == 'a' and self.cell is not None:
            self.cell['links'].append(dict(attrs).get('href', ''))

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if self.hidden: return
        if tag in ('td', 'th'): self.cell = None
        if tag == 'tr' and self.stack:
            self.rows.append(self.stack.pop())
            self.cell = None

    def handle_data(self, data):
        if self.hidden: return
        self.text.append(data)
        if self.cell is not None: self.cell['text'].append(data)


def calendar_urls(as_of):
    month = as_of.replace(day=1)
    prior = (month - timedelta(days=1)).replace(day=1)
    return [ROOT + day.strftime('%y%m') + '.htm' for day in (prior, month)]


def parse_calendar(raw, *, source_url):
    match = re.fullmatch(re.escape(ROOT) + r'(\d{2})(\d{2})\.htm', source_url)
    if not match: raise ValueError('auction_calendar_url')
    year, month = 2000 + int(match[1]), int(match[2]); date(year, month, 1)
    doc = _Document(raw)
    expected = f'入札カレンダー:令和{year-2018}年{month}月'
    if expected not in _norm(''.join(doc.text)):
        raise ValueError('auction_calendar_period')
    results = []; seen = set()
    for cells in doc.rows:
        texts = [_norm(''.join(cell['text'])) for cell in cells]
        if len(texts) != 6: continue
        tenor = re.fullmatch(r'(10|20|30|40)年利付国債(?:\(第\d+回\))?', texts[1])
        if not tenor: continue
        day = re.fullmatch(r'(\d+)月(\d+)日\([月火水木金土日]\)', texts[0])
        if not day or int(day[1]) != month: raise ValueError('auction_calendar_session')
        session = date(year, month, int(day[2])).isoformat()
        key = session, int(tenor[1])
        if key in seen: raise ValueError('auction_calendar_duplicate')
        seen.add(key)
        # Only the price/yield result column, never supplementary noncompetitive results.
        links = [urljoin(source_url, href) for href in cells[4]['links']]
        target = ROOT + 'nyusatsu/resul' + session.replace('-', '') + '.htm'
        if len(links) > 1 or (links and links != [target]):
            raise ValueError('auction_result_link')
        results.append({'sessionDate': session, 'tenorYears': int(tenor[1]),
                        'sourceUrl': target if links else None})
    return sorted(results, key=lambda row: (row['sessionDate'], row['tenorYears']))


def _money(text):
    text = _norm(text)
    integer = r'(?:\d{1,3}(?:,\d{3})+|\d+)'
    pattern = ''.join(f'(?:({integer}){unit})?' for unit in ('兆', '億', '万')) + f'({integer})?円'
    match = re.fullmatch(pattern, text)
    if not match or not any(match.groups()): raise ValueError('auction_amount')
    value = sum(int(cell.replace(',', '')) * multiplier for cell, multiplier in
                zip(match.groups(), (10**12, 10**8, 10**4, 1)) if cell)
    if not 0 < value <= 10**15: raise ValueError('auction_amount_range')
    return value


def _yield(text):
    match = re.fullmatch(r'\(?(-?\d+\.\d{1,3})%\)?', text)
    if not match: raise ValueError('auction_yield')
    value = Decimal(match[1])
    if not -5 < value < 30: raise ValueError('auction_yield_range')
    return value


def parse_result(raw, *, expected, acquired_at):
    # Receipt is actual knowledge time; an official date is not a publication clock.
    from argus_jp_fiscal_monitor import instant, digest
    receipt = instant(acquired_at)
    session = date.fromisoformat(expected['sessionDate']); tenor = expected['tenorYears']
    target = ROOT + 'nyusatsu/resul' + session.strftime('%Y%m%d') + '.htm'
    if tenor not in TENORS or expected.get('sourceUrl') != target:
        raise ValueError('auction_expected_identity')
    from zoneinfo import ZoneInfo
    if session > receipt.astimezone(ZoneInfo('Asia/Tokyo')).date():
        raise ValueError('auction_future_date')
    doc = _Document(raw); text = _norm(''.join(doc.text))
    stamp = f'令和{session.year-2018}年{session.month}月{session.day}日'
    title = re.search(rf'{tenor}年利付国債\(第(\d+)回\)の入札結果', text)
    if not title or stamp not in text or '第II非価格競争入札結果' in text:
        raise ValueError('auction_result_identity')
    rows = [[_norm(''.join(c['text'])) for c in row] for row in doc.rows if len(row) == 4]
    competitive = tenor != 40
    if competitive:
        starts = [i for i, row in enumerate(rows) if row[1] == '価格競争入札について']
        if len(starts) != 1: raise ValueError('auction_competitive_section')
        end = next((i for i in range(starts[0]+1, len(rows)) if re.fullmatch(r'\d+\.', rows[i][0])), len(rows))
        rows = rows[starts[0]+1:end]
    def cell(label):
        values = [row[3] for row in rows if row[1] == label]
        if len(values) != 1: raise ValueError('auction_unique_field')
        return values[0]
    bids = _money(cell('(1)応募額' if competitive else '応募額'))
    accepted = _money(cell('(2)募入決定額' if competitive else '募入決定額'))
    if bids < accepted: raise ValueError('auction_amount_order')
    if competitive:
        maximum = _yield(cell('(募入最高利回り)'))
        average = _yield(cell('(募入平均利回り)'))
        if maximum < average: raise ValueError('auction_yield_order')
    else:
        maximum = _yield(cell('応募者利回り'))
        if cell('(募入最高利回り)') != '': raise ValueError('auction_uniform_layout')
        average = None
    body = {'schemaVersion':'jp-jgb-auction-observation-v1','sessionDate':session.isoformat(),
        'tenorYears':tenor,'issueNumber':int(title[1]),
        'auctionMethod':'PRICE_COMPETITIVE' if competitive else 'UNIFORM_YIELD',
        'competitiveBidAmountJpy':bids,'competitiveAcceptedAmountJpy':accepted,
        'bidToCover':float(Decimal(bids)/Decimal(accepted)),
        'highestAcceptedYieldPct':float(maximum),
        'averageAcceptedYieldPct':float(average) if average is not None else None,
        'yieldTailBp':float((maximum-average)*100) if average is not None else None,
        'publishedDate':session.isoformat(),'publishedAt':None,'knownAt':acquired_at,
        'acquiredAt':acquired_at,'sourceUrl':target,'sourceHash':sha256(raw).hexdigest(),
        'availabilityBasis':'ACTUAL_RECEIPT','historicalVintageVerified':False,
        'acquisitionStatus':'AVAILABLE','actionAuthority':False,'predictivePerformance':'UNVALIDATED'}
    body['id'] = 'jgb-auction-' + digest({k:v for k,v in body.items()
        if k not in ('knownAt','acquiredAt','sourceHash')})
    return body


def ledger_series():
    return {f'jp.market.jgb.auction.{tenor}y': ('RATIO', f'{tenor}年国債入札の応募倍率', 'mof', 'official')
            for tenor in TENORS}


def ledger_candidates(rows):
    """Store complete result metadata in the shared ledger, never a second store."""
    from copy import deepcopy
    result = []
    for row in rows:
        sid = f'jp.market.jgb.auction.{row["tenorYears"]}y'
        if sid not in ledger_series() or row.get('actionAuthority') is not False:
            raise ValueError('auction_ledger_identity')
        result.append({'seriesId':sid, 'periodEnd':row['sessionDate'],
            'availableFrom':row['knownAt'], 'observedAt':row['acquiredAt'],
            'publishedAt':None, 'source':row['sourceUrl'], 'sourceKind':'official',
            'value':row['bidToCover'], 'unit':'RATIO', 'status':'live',
            'metadata':{'jgbAuctionInput':deepcopy(row), 'excludeFromEffective':True,
                'observedAtBasis':'ACTUAL_RECEIPT',
                'reason':'Auction demand observation is not fiscal effective interest or a stock prediction'}})
    return result


def _eligible(state, *, as_of=None):
    from argus_jp_fiscal_monitor import instant
    cutoff = instant(as_of) if as_of is not None else None
    rolled = set(state.get('rolledBackImports') or []); latest = {}
    for observation in state.get('observations', ()):
        if observation.get('importId') in rolled: continue
        row = observation.get('metadata', {}).get('jgbAuctionInput')
        if not isinstance(row, dict): continue
        sid = f'jp.market.jgb.auction.{row.get("tenorYears")}y'
        if sid not in ledger_series() or observation.get('seriesId') != sid:
            raise ValueError('auction_saved_identity')
        at, known = instant(observation['availableFrom']), instant(row['knownAt'])
        if cutoff is not None and (at > cutoff or known > cutoff): continue
        key = sid, row['sessionDate']
        if key not in latest or at >= latest[key][0]: latest[key] = at, row
    return latest


def missing_candidates(state, candidates):
    # Latest revision comparison supports a correction back to an earlier value.
    result = []
    for row in candidates:
        latest = _eligible(state, as_of=row['availableFrom'])
        if latest.get((row['seriesId'], row['periodEnd']), (None, {}))[1].get('id') != row['metadata']['jgbAuctionInput']['id']:
            result.append(row)
    return result


def saved_rows(state, *, as_of):
    from copy import deepcopy
    rows = _eligible(state, as_of=as_of)
    return [deepcopy(rows[key][1]) for key in sorted(rows)]


def projection(state, *, as_of, expected=(), acquisition='NOT_RUN'):
    """Use only received vintages; a pending auction never erases prior results."""
    from argus_jp_fiscal_monitor import digest
    rows = saved_rows(state, as_of=as_of); latest = {}
    for row in rows:
        tenor = row['tenorYears']
        if tenor not in latest or row['sessionDate'] >= latest[tenor]['sessionDate']:
            latest[tenor] = row
    expected_by = {}
    for row in expected:
        tenor = row['tenorYears']
        if tenor not in expected_by or row['sessionDate'] >= expected_by[tenor]['sessionDate']:
            expected_by[tenor] = row
    series = {}
    for tenor in TENORS:
        row = latest.get(tenor); target = expected_by.get(tenor)
        current = bool(row and target and row['sessionDate'] == target['sessionDate'] and target.get('sourceUrl'))
        status = 'AVAILABLE' if current else 'UPDATE_WAIT' if target else 'NOT_IN_BOUNDED_CALENDAR'
        series[str(tenor)] = {'status':status, 'expectedSessionDate':target['sessionDate'] if target else None,
            'resultLinkPublished':bool(target and target.get('sourceUrl')), 'latestResult':row}
    body = {'schemaVersion':'jp-jgb-auction-projection-v1', 'acquisitionStatus':acquisition,
        'series':series, 'actionAuthority':False, 'predictivePerformance':'UNVALIDATED',
        'historicalVintageVerified':False}
    body['id'] = 'jgb-auctions-' + digest({'acquisition':acquisition,
        'series':{key:{'status':row['status'], 'expected':row['expectedSessionDate'],
                    'resultLinkPublished':row['resultLinkPublished'],
                    'result':(row['latestResult'] or {}).get('id')} for key,row in series.items()}})
    return body


def collect(state, *, as_of, read, max_requests=6):
    """At most two calendars and one result per tenor; read returns completion time."""
    from argus_jp_fiscal_monitor import instant
    from zoneinfo import ZoneInfo
    if isinstance(max_requests,bool) or max_requests not in (5,6):
        raise ValueError('auction_request_budget')
    today = instant(as_of).astimezone(ZoneInfo('Asia/Tokyo')).date()
    expected = {}; errors = {}; requests = 0; rows = []; finished = instant(as_of)
    for url in calendar_urls(today):
        try:
            requests += 1
            raw, acquired_at = read(url, 256_000)
            at = instant(acquired_at)
            if at < instant(as_of): raise ValueError('auction_receipt_precedes_request')
            finished = max(finished, at)
            calendar = parse_calendar(raw, source_url=url)
            for row in calendar:
                if date.fromisoformat(row['sessionDate']) > today: continue
                tenor = row['tenorYears']
                if tenor not in expected or row['sessionDate'] > expected[tenor]['sessionDate']:
                    expected[tenor] = row
        except Exception:
            errors[url.rsplit('/', 1)[-1]] = 'CALENDAR_ACQUISITION_FAILED'
    # Partial calendar coverage cannot determine the latest auction safely.
    if not errors:
        existing = _eligible(state, as_of=as_of)
        # A reserved archive read must not starve the same missing tenor.
        order = sorted(TENORS,key=lambda tenor:(
            (f'jp.market.jgb.auction.{tenor}y',(expected.get(tenor) or {}).get('sessionDate')) in existing, tenor))
        for tenor in order:
            target = expected.get(tenor)
            if not target or not target.get('sourceUrl'): continue
            if requests >= max_requests: break
            try:
                requests += 1
                raw, acquired_at = read(target['sourceUrl'], 256_000)
                at = instant(acquired_at)
                if at < instant(as_of): raise ValueError('auction_receipt_precedes_request')
                finished = max(finished, at)
                rows.append(parse_result(raw, expected=target, acquired_at=acquired_at))
            except Exception:
                errors[str(tenor)] = 'RESULT_ACQUISITION_FAILED'
    status = 'FAILED' if errors else 'AVAILABLE' if len(rows) == len(TENORS) else 'UPDATE_WAIT'
    return {'candidates':missing_candidates(state, ledger_candidates(rows)),
        'expected':list(expected.values()), 'acquisitionStatus':status,
        'requests':requests, 'errors':errors, 'completedAt':finished.isoformat()}
