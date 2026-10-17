"""Bounded official monthly backfill into the existing valuation ledger series.

Archive rows retain today's actual source receipt and retrospective status.
This collector does not invent historical availability or import balances.
"""
from __future__ import annotations

import calendar
import hashlib
import io
import logging
import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from argus_jpx_credit_valuation import extract_monthly_text, ledger_observation, audited_ledger_observation

INDEX = 'https://www.jpx.co.jp/markets/statistics-equities/monthly/index.html'
MAX_BYTES = 3 * 1024 * 1024


def official_url(url):
    p = urlparse(url)
    if (p.scheme != 'https' or p.netloc != 'www.jpx.co.jp' or p.query or p.fragment
            or '..' in p.path or '%' in p.path
            or not p.path.startswith('/markets/statistics-equities/monthly/')
            or not p.path.endswith(('.html', '.pdf'))):
        raise ValueError('jpx_monthly_source_invalid')
    return url


def read(url, limit):
    class Redirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            official_url(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    request = Request(official_url(url), headers={'User-Agent':'Mozilla/5.0 (ARGUS credit valuation)'})
    with build_opener(Redirect()).open(request, timeout=30) as response:
        official_url(response.geturl())
        payload = response.read(limit + 1)
        if len(payload) > limit:
            raise ValueError('jpx_monthly_size')
        return payload


class IndexLinks(HTMLParser):
    def __init__(self, base):
        super().__init__(); self.base=base; self.option=None; self.years={}; self.row=None; self.links=[]; self.credit=[]

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='option': self.option=attrs.get('value')
        if tag=='tr': self.row=[]; self.links=[]
        if tag=='a' and self.row is not None: self.links.append(attrs.get('href',''))

    def handle_data(self, text):
        if self.option and re.fullmatch(r'20\d\d年',text.strip()):
            year=int(text.strip()[:-1]); url=official_url(urljoin(self.base,self.option))
            if year in self.years and self.years[year]!=url: raise ValueError('jpx_monthly_year_ambiguous')
            self.years[year]=url
        if self.row is not None: self.row.append(text)

    def handle_endtag(self, tag):
        if tag=='option': self.option=None
        if tag=='tr' and self.row is not None:
            if '信用取引現在高' in ''.join(self.row):
                if self.credit: raise ValueError('jpx_monthly_credit_ambiguous')
                self.credit=list(self.links)
            self.row=None


def parse_index(payload, base=INDEX):
    if len(payload)>1024*1024: raise ValueError('jpx_monthly_index_size')
    out=IndexLinks(official_url(base)); out.feed(payload.decode('utf-8')); out.close()
    return out


def selected_sources(first, *, start_year=2016, end_year=2026, fetcher=read):
    if not 2016<=start_year<=end_year<=2026: raise ValueError('jpx_monthly_year_range')
    if not set(range(start_year,end_year+1))<=first.years.keys(): raise ValueError('jpx_monthly_years_missing')
    sources=[]
    for year in range(start_year,end_year+1):
        base=first.years[year]
        page=first if base==INDEX else parse_index(fetcher(base,1024*1024),base)
        if not page.credit: raise ValueError('jpx_monthly_credit_missing')
        months={}
        for link in page.credit:
            url=official_url(urljoin(base,link))
            match=re.search(r'sinyou(\d{2})(\d{2})\.pdf$',url)
            if not match or int(match[1])+2000!=year: raise ValueError('jpx_monthly_period_invalid')
            month=int(match[2])
            if not 1<=month<=12 or (month in months and months[month]!=url): raise ValueError('jpx_monthly_period_ambiguous')
            months[month]=url
        selected=sorted(m for m in months if m in (3,6,9,12))
        if max(months) not in selected: selected.append(max(months))
        if year<end_year and set(selected)!={3,6,9,12}: raise ValueError('jpx_monthly_quarters_missing')
        sources.extend(months[m] for m in sorted(selected))
    if len(sources)>44: raise ValueError('jpx_monthly_source_count')
    return sources


def extract_pdf(payload):
    if len(payload)>MAX_BYTES or not payload.startswith(b'%PDF-'): raise ValueError('jpx_monthly_pdf_invalid')
    import pdfplumber
    # Cosmetic PDF-color warnings can contain source tokens. They are not
    # input-validation evidence and must not leak into the public job log.
    logger=logging.getLogger('pdfminer.pdfinterp'); previous=logger.disabled
    logger.disabled=True
    try:
        with pdfplumber.open(io.BytesIO(payload)) as book:
            if not 1<=len(book.pages)<=6: raise ValueError('jpx_monthly_page_count')
            texts=[page.extract_text(x_tolerance=1) or '' for page in book.pages]
            candidates=[text for text in texts if '社内対当' in text]
            if len(candidates)!=1: raise ValueError('jpx_monthly_page_ambiguous')
            return extract_monthly_text(candidates[0])
    finally:
        logger.disabled=previous


def held_periods(table):
    """Only the existing server's audited calculation history excludes rows."""
    found=set()
    for series in table:
        if (series.get('seriesId')!='credit.valuation_loss_pct' or series.get('sourceKind')!='derived'
                or series.get('acquisition')!='jpx_official_formula'): continue
        audits=[item.get('auditedObservation') for item in series.get('history') or []]
        if not any(audit and audited_ledger_observation(audit) for audit in audits): continue
        for item in series.get('history') or []:
            if re.fullmatch('[0-9a-f]{64}',str(item.get('calculationDigest') or '')):
                found.add(item['periodEnd'])
    return found


def collect(table, *, start_year=2016, end_year=2026, fetcher=read, parser=extract_pdf, clock=None):
    clock=clock or (lambda:datetime.now(timezone.utc).isoformat())
    first=parse_index(fetcher(INDEX,1024*1024))
    sources=selected_sources(first,start_year=start_year,end_year=end_year,fetcher=fetcher)
    known=held_periods(table); by={}
    for url in sources:
        payload=fetcher(url,MAX_BYTES); received=clock(); digest=hashlib.sha256(payload).hexdigest()
        match=re.search(r'sinyou(\d{2})(\d{2})\.pdf$',url)
        report_year,report_month=int(match[1])+2000,int(match[2])
        report_end=date(report_year,report_month,calendar.monthrange(report_year,report_month)[1])
        for record in parser(payload):
            period=record['periodEnd']
            if date.fromisoformat(period)>report_end: raise ValueError('jpx_monthly_future_period')
            if period<'2016-01-01': continue
            if period in by:
                if by[period]['metadata']['valuationCalculation']['inputs']!=record['inputs']:
                    raise ValueError('jpx_monthly_input_conflict')
                continue
            by[period]=ledger_observation(record,url=url,sha256=digest,received_at=received,retrospective=True)
    if not by or len(by)>600: raise ValueError('jpx_monthly_row_count')
    return [by[period] for period in sorted(by) if period not in known]
