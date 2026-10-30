"""日銀の公表済み決定文を読む。予定・受領を公表時刻に置き換えない。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import hashlib
import re
import unicodedata
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
MAX_DOCUMENT_BYTES = 1024 * 1024
MAX_INDEX_BYTES = 512 * 1024


def _compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text))


def _instant(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timezone_required')
    return parsed.astimezone(timezone.utc)


class _Index(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.cells, self.links = [], None, []
        self.cell, self.anchor = None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.cells, self.links = [], []
        elif self.cells is not None and tag in ('td', 'th'):
            self.cell = []
        elif self.cells is not None and tag == 'a':
            self.anchor = [dict(attrs).get('href', ''), []]

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)
        if self.anchor is not None:
            self.anchor[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'a' and self.anchor is not None:
            self.links.append((self.anchor[0], ''.join(self.anchor[1])))
            self.anchor = None
        elif tag in ('td', 'th') and self.cell is not None:
            self.cells.append(''.join(self.cell))
            self.cell = None
        elif tag == 'tr' and self.cells is not None:
            self.rows.append((self.cells, self.links))
            self.cells, self.cell, self.anchor = None, None, None


def policy_reference(html, *, event_date):
    target = date.fromisoformat(event_date)
    base = f'https://www.boj.or.jp/mopo/mpmdeci/mpr_{target.year}/index.htm'
    parser = _Index()
    parser.feed(html)
    urls = set()
    for cells, links in parser.rows:
        if not cells:
            continue
        match = re.fullmatch(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', _compact(cells[0]))
        if not match or date(*map(int, match.groups())) != target:
            continue
        for href, title in links:
            title = _compact(title).split('[PDF', 1)[0]
            if title not in ('当面の金融政策運営について', '金融市場調節方針の変更について'):
                continue
            url = urljoin(base, href)
            parsed = urlsplit(url)
            if (parsed.scheme == 'https' and parsed.netloc == 'www.boj.or.jp'
                    and not parsed.query and not parsed.fragment and
                    re.fullmatch(rf'/mopo/mpmdeci/mpr_{target.year}/k\d{{6}}[a-z]?\.pdf', parsed.path)):
                urls.add(url)
    if len(urls) != 1:
        raise ValueError('official_policy_reference_unavailable')
    return urls.pop()


def extract_document(raw):
    if not isinstance(raw, bytes) or not raw.startswith(b'%PDF-') or len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError('invalid_policy_document')
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(raw), strict=True)
    if reader.is_encrypted or not 1 <= len(reader.pages) <= 8:
        raise ValueError('invalid_policy_document_pages')
    texts = []
    for page in reader.pages:
        # Bound the decoded content before text extraction too.
        content = page.get_contents()
        if content is not None and len(content.get_data()) > 2 * 1024 * 1024:
            raise ValueError('policy_page_content_too_large')
        texts.append(page.extract_text() or '')
        if sum(map(len, texts)) > 200000:
            raise ValueError('policy_text_too_large')
    return '\n'.join(texts)


def parse_document(text, *, event_date, received_at, source_url, document_sha256):
    target, received = date.fromisoformat(event_date), _instant(received_at)
    source = urlsplit(source_url)
    if (source.scheme != 'https' or source.netloc != 'www.boj.or.jp'
            or source.query or source.fragment or not re.fullmatch(
                rf'/mopo/mpmdeci/mpr_{target.year}/k{target:%y%m%d}[a-z]?\.pdf', source.path)
            or not re.fullmatch(r'[0-9a-f]{64}', document_sha256)):
        raise ValueError('policy_source_identity_invalid')
    compact = _compact(text)
    header = re.search(r'(20\d{2})年(\d{1,2})月(\d{1,2})日', compact[:200])
    if not header or date(*map(int, header.groups())) != target or target > received.astimezone(JST).date():
        raise ValueError('policy_date_mismatch')
    if '日本銀行' not in compact[:200] or '金融市場調節方針' not in compact:
        raise ValueError('policy_document_identity_invalid')
    decision = compact.split('以上', 1)[0]
    rates = re.findall(r'無担保コールレート[（(]オーバーナイト物[）)]を[、,]?(-?\d+(?:\.\d+)?)%程度で推移するよう促す', decision)
    if len(rates) != 1 or not -5 <= float(rates[0]) <= 20:
        raise ValueError('policy_rate_unavailable')
    published = None
    notice = compact.split('公表日時', 1)[-1] if '公表日時' in compact else ''
    clocks = re.findall(r'当面の金融政策運営について[―—−ー\-]+(\d{1,2})月(\d{1,2})日\([月火水木金土日]\)(\d{1,2}):(\d{2})(予定)?', notice)
    if len(clocks) == 1 and not clocks[0][-1]:
        month, day, hour, minute = map(int, clocks[0][:4])
        published = datetime(target.year, month, day, hour, minute, tzinfo=JST).astimezone(timezone.utc)
        if published.astimezone(JST).date() != target or published > received:
            raise ValueError('policy_publication_time_invalid')
    elif clocks:
        raise ValueError('policy_publication_time_ambiguous')
    rate = float(rates[0])
    metrics = {'policyRatePct': rate}
    headline = f'政策金利 {rate:g}%'
    # The same document cites the old pace too. Only the current decision clause
    # can supply this metric; never pick the first number on a page.
    pace = re.search(r'本日の金融政策決定会合において[、,]ETFの売却について[、,].{0,180}?年間の売却ペースを([0-9,]+)億円程度', decision)
    if pace:
        amount = int(pace[1].replace(',', ''))
        if 0 < amount <= 1000000:
            metrics['etfAnnualSalesOkuYen'] = amount
            starts = re.findall(r'(20\d{2})年(1[0-2]|[1-9])月から実施', compact)
            start = ''
            if len(starts) == 1:
                year, month = map(int, starts[0])
                if (year, month) >= (target.year, target.month):
                    metrics['etfAnnualSalesEffectiveMonth'] = f'{year:04d}-{month:02d}'
                    start = f'{year}/{month}から'
            headline += f'／ETF売却計画 {start}年{amount:,}億円'
    released = published.isoformat().replace('+00:00', 'Z') if published else None
    out = {'schemaVersion': 'macro-result-v1', 'available': True, 'status': 'live', 'source': 'BOJ', 'sourceUrl': source_url,
           'releasedAt': released, 'receivedAt': received_at, 'availableFrom': received_at,
           'availabilityBasis': 'RESPONSE_RECEIPT', 'historicalVintageVerified': False,
           'sourceDocumentSha256': document_sha256, 'documentDate': event_date,
           'headline': headline, 'metrics': metrics,
           'metricDefinitions': {'policyRatePct': {'labelJa': '無担保コール翌日物の誘導目標', 'unit': '%'},
                                 'etfAnnualSalesOkuYen': {'labelJa': 'ETFの年間売却額（簿価）', 'unit': '億円/年'}},
           'limitationsJa': [] if published else ['公式文書の公表時刻は未確認']}
    if published:
        out['publicationTimeEvidence'] = {'basis': 'OFFICIAL_DOCUMENT_PUBLICATION_NOTICE',
            'eventTimeUtc': released, 'precision': 'MINUTE', 'sourceUrl': source_url,
            'sourceDocumentSha256': document_sha256, 'receivedAt': received_at}
    return out


def _read(get, url, maximum):
    response = get(url, headers={'User-Agent': 'ARGUS-official-result/1.0'},
                   timeout=(4, 10), allow_redirects=False, stream=True)
    try:
        if response.status_code != 200 or response.url != url or response.history:
            raise ValueError('official_policy_http_unavailable')
        result = bytearray()
        for chunk in response.iter_content(65536):
            if chunk:
                if len(result) + len(chunk) > maximum:
                    raise ValueError('official_policy_response_too_large')
                result.extend(chunk)
        return bytes(result)
    finally:
        response.close()


def fetch(get, event, *, now_iso, clock=None):
    target = date.fromisoformat(str(event.get('eventDate') or event.get('date') or '')[:10])
    if target > _instant(now_iso).astimezone(JST).date():
        raise ValueError('future_policy_event')
    base = f'https://www.boj.or.jp/mopo/mpmdeci/mpr_{target.year}/index.htm'
    index = _read(get, base, MAX_INDEX_BYTES).decode('utf-8-sig')
    url = policy_reference(index, event_date=target.isoformat())
    raw = _read(get, url, MAX_DOCUMENT_BYTES)
    # Sample AFTER both HTTP responses. The request-start clock is not receipt.
    received = clock() if clock is not None else datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    return parse_document(extract_document(raw), event_date=target.isoformat(),
        received_at=received, source_url=url, document_sha256=hashlib.sha256(raw).hexdigest())
