#!/usr/bin/env python3
"""Offline extraction of one reviewed CAO edition. Never run in a request path.

Needs pypdf in the research environment only. The input PDF is retained outside
of the product. A changed edition requires a new definition/layout review.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

SOURCE_SHA = '7ed2aac791cb650c7ba975955bc562a84936fa0adf0927bb862baeb575e67cbe'
SOURCE_URL = 'https://www5.cao.go.jp/keizai2/keizai-syakai/shisan/2607hontai.pdf'
CASES = {'growth_1': '成長戦略実現ケース①', 'growth_2': '成長戦略実現ケース②', 'baseline': '現状投影ケース'}
LABELS = {'nominal_growth': '名目GDP成長率', 'effective_rate': '実効金利',
    'primary_balance': '国・地方の基礎的財政収支（対名目GDP比）',
    'debt_ratio': '国・地方の公債等残高（対名目GDP比）', 'market_yield': '名目長期金利'}


def extract(path):
    from pypdf import PdfReader
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('unreviewed_source_edition')
    text = PdfReader(path).pages[31].extract_text()
    output = {}
    for case, heading in CASES.items():
        block = text.split(heading, 1)[1]
        lines = block.splitlines()
        years = [int(x) for x in re.findall(r'20\d{2}', lines[1].replace('203 9', '2039'))]
        if years != list(range(2024, 2041)):
            raise ValueError('unexpected_year_columns')
        output[case] = {}
        for metric, label in LABELS.items():
            line = next(line for line in lines if line.startswith(label + ' '))
            cells = [re.sub(r'\s+', '', x).replace('▲', '-') for x in re.findall(r'\(([^()]*)\)', line)]
            if len(cells) != len(years) or any(not re.fullmatch(r'-?\d+\.\d', x) for x in cells):
                raise ValueError('unexpected_numeric_cells:' + metric)
            output[case][metric] = cells  # Preserve negative rounded zero.
    return {'schemaVersion': 'jp-fiscal-reviewed-table-v1', 'editionId': 'cao-medium-term-20260730',
        'sourceUrl': SOURCE_URL, 'sourceSha256': SOURCE_SHA, 'sourcePage': 29,
        'publishedDate': '2026-07-30', 'publishedAt': None, 'years': years,
        'actualThroughFiscalYear': 2024, 'cases': output,
        'definition': {'country': 'JP', 'periodBasis': 'FISCAL_YEAR', 'frequency': 'ANNUAL',
            'priceBasis': 'NOMINAL', 'unit': 'PERCENT',
            'governmentScope': 'CENTRAL_AND_LOCAL',
            'debtDefinition': 'ORDINARY_JGB_LOCAL_BONDS_ALLOCATION_TAX_BORROWING',
            'balanceCoverage': 'EXCLUDES_RECONSTRUCTION_GX_AI_SEMICONDUCTOR',
            'accountingBasis': 'CAO_SNA_FLOW_BUDGET_DEBT_BRIDGE',
            'effectiveRateDenominator': 'PREVIOUS_FISCAL_YEAR_END_DEBT'},
        'limitations': ['一般政府総債務・純債務ではない。社会保障基金発行の子ども特例債は対象外。',
            'PBはSNAの執行時点、公債等残高は予算年度。その他要因をゼロとしない。',
            '将来値は内閣府のケース別試算でありARGUSの予測ではない。',
            '表の一桁丸め値。掲載時刻未確認。資料の実効金利を採用し、純利払費から再算出しない。'],
        'validation': {'sourceTableChecked': True, 'predictivePerformance': 'UNVALIDATED',
            'productionObserved': False}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('pdf'); parser.add_argument('output')
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(extract(args.pdf), ensure_ascii=False, indent=2)+'\n')
