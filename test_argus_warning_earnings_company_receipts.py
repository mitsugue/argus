"""Synthetic historical replay contracts; no real prices or receipt changes."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import unittest

from argus_warning_candidates import earnings_rule
from argus_warning_earnings_study import study as candidate


def fixture():
    days = [(date(2026, 9, 1) + timedelta(days=i)).isoformat() for i in range(11)]
    members = [str(1000+i) for i in range(225)]
    previous = dict(summary=dict(Code='1005', DiscDate='2026-08-20', DiscNo='prior',
        CurFYEn='2026-08-31', FOP=100), observationId='synthetic-prior',
        publishedAt='2026-08-20T07:00:00Z', knownAt='2026-08-20T07:00:00Z', receivedAt='2026-08-20T07:00:00Z')
    current = dict(summary=dict(Code='1005', DiscDate=days[-1], DiscNo='initial',
        CurFYEn='2026-08-31', NxtFYEn='2027-08-31', FOP='', NxFOP=110,
        CurPerType='FY', DocType='FYFinancialStatements_Consolidated_IFRS'),
        observationId='synthetic-current', publishedAt=days[-1]+'T07:00:00Z',
        knownAt=days[-1]+'T07:00:00Z', receivedAt=days[-1]+'T07:00:00Z')
    return dict(sessions=days, nikkei_rows=[dict(date=d, instrumentId='NIKKEI_225_INDEX',
        close=40000, availableFrom=d+'T07:00:00Z') for d in days],
        financial_rows=[previous, current], membership_by_day={d:list(members) for d in days},
        stock_bars={}, topix_rows=[], coverage_by_day={d:dict(memberCodes=list(members),
        complete=True, knownAt=d+'T08:00:00Z', receivedAt=d+'T08:00:00Z') for d in days},
        cutoff=days[-1]+'T09:00:00Z', company_coverage={'1005':dict(complete=True,
        receivedAt=days[-1]+'T08:00:00Z', firstDisclosureDay='2026-08-20',
        lastDisclosureDay=days[-1], observationIds=['synthetic-prior', 'synthetic-current'])})


class ReplayContracts(unittest.TestCase):
    def test_replay_must_match_core_initial_outlook_admission(self):
        data = fixture(); before = deepcopy(data)
        core = {k:v for k,v in data.items() if k != 'nikkei_rows'}
        decision = earnings_rule(**core)
        self.assertEqual((decision['state'], decision['goodEarningsCount']), ('CLEAR', 0))
        without = {k:v for k,v in data.items() if k != 'company_coverage'}
        self.assertEqual(candidate(**without)['condition']['inputDays'], 0)
        self.assertEqual(candidate(**data)['condition']['inputDays'], 1)
        self.assertEqual(data, before)

    def test_default_replay_keeps_entire_existing_artifact_unchanged(self):
        data = fixture(); data.pop('company_coverage')
        legacy = candidate(**data)
        digest = hashlib.sha256(json.dumps(legacy,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest, '09e0578f19b91b8ba7641201937df3d45a5e86ecb64579f1fc05858b7e713eef')

    def test_receipt_rejections_do_not_admit_missing_forecast(self):
        for kind in ('future', 'stale', 'partial', 'short_span', 'missing_id', 'unread_id', 'revision', 'current_year'):
            with self.subTest(kind=kind):
                data = fixture(); proof=data['company_coverage']['1005']; s=data['financial_rows'][-1]['summary']
                if kind == 'future': proof['receivedAt']='2026-09-12T00:00:00Z'
                if kind == 'stale': proof['receivedAt']='2026-08-20T07:00:00Z'
                if kind == 'partial': proof['complete']=False
                if kind == 'short_span': proof['firstDisclosureDay']=s['DiscDate']
                if kind == 'missing_id': proof['observationIds']=['synthetic-prior']
                if kind == 'unread_id': proof['observationIds'].append('unread')
                if kind == 'revision': s['DocType']='ForecastRevision'
                if kind == 'current_year': s.update(CurFYEn='2028-08-31', NxtFYEn='2029-08-31', FOP=110, NxFOP='')
                before=deepcopy(data)
                self.assertEqual(candidate(**data)['condition']['inputDays'], 0)
                self.assertEqual(data, before)

    def test_reconstruction_never_backdates_company_receipt(self):
        data=fixture(); data['cutoff']='2026-10-02T09:00:00Z'
        for row in data['financial_rows']:
            row['knownAt']=row['receivedAt']='2026-10-01T00:00:00Z'
        data['company_coverage']['1005']['receivedAt']='2026-10-01T01:00:00Z'
        before=deepcopy(data); result=candidate(**data, reconstruct=True)
        self.assertEqual(result['condition']['inputDays'], 0)
        self.assertEqual(result['companyReceiptBasis'], 'ACTUAL_RETAINED_RECEIPTS_NEVER_BACKDATED')
        self.assertFalse(result['historicalVintageVerified'])
        self.assertEqual(data, before)

    def test_same_year_prior_uses_revision_comparison_without_initial_exception(self):
        data=fixture(); data['financial_rows'][-1]['summary'].update(FOP=110, NxFOP='')
        core={k:v for k,v in data.items() if k != 'nikkei_rows'}
        self.assertEqual(earnings_rule(**core)['goodEarningsCount'], 1)
        data['company_coverage']['1005']['complete']=False
        self.assertEqual(candidate(**data)['condition']['inputDays'], 1)

    def test_company_receipt_identity_changes_the_artifact_even_if_gated(self):
        data=fixture(); data['company_coverage']['1005']['receivedAt']='2026-09-12T00:00:00Z'
        one=candidate(**data)
        data['company_coverage']['1005']['receivedAt']='2026-09-13T00:00:00Z'
        two=candidate(**data)
        self.assertEqual(one['condition'], two['condition'])
        self.assertNotEqual(one['sourceDigest'], two['sourceDigest'])
        self.assertNotEqual(one['artifactId'], two['artifactId'])

    def test_bound_and_shape_reject_before_replay(self):
        for proof in ([], {'1005':None}, {'1005':dict(observationIds=None)},
                      {'1005':dict(observationIds=['x']*30001)}):
            with self.subTest(shape=type(proof).__name__):
                data=fixture(); data['company_coverage']=proof
                with self.assertRaisesRegex(ValueError, 'company_receipt_bound'):
                    candidate(**data)

    def test_no_probability_action_or_forecast_performance_claim(self):
        result=candidate(**fixture())
        self.assertEqual(result['condition']['evaluated'], 0)
        self.assertIsNone(result['predictiveProbabilities'])
        self.assertFalse(result['actionAuthority'])
        self.assertEqual(result['validationStatus'], 'UNVALIDATED')
        self.assertEqual(result['schemaVersion'], 'jp-warning-earnings-original-replay-v2')

if __name__ == '__main__':
    unittest.main(verbosity=2)
