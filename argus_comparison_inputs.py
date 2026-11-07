"""Prepare historical reaction cache views without changing kept observations.

The derived research batch digests are not consumed by sealed episodes. A
refreshed batch can invalidate every candidate while producing the same
episodes and study. Remove only those two annotations from uniquely keyed,
explicitly reconstructed research reactions. Ordinary observations, state
history, conditions and event-source identities remain exact. Any duplicate
PIT revision keeps the complete original inputs:
full-row conflict checks must still see differing batch digests.
"""
from collections.abc import Mapping
import re

GROUPS = ('states', 'conditions', 'reactions', 'research')
_BATCH_DIGESTS = frozenset(('sourceRowsHash', 'sourceSha256'))
_DIGEST = re.compile(r'[a-f0-9]{64}\Z')


def _revision_key(row):
    revision = row.get('revision', 0)
    if type(revision) is not int or revision < 0:
        return None
    instrument = str(row.get('instrumentId') or row.get('instrument') or row.get('symbol') or 'MARKET').upper()
    field = str(row.get('seriesId') or row.get('field') or row.get('kind') or '')
    if not field and all(key in row for key in ('open', 'high', 'low', 'close', 'volume')):
        field = 'OHLCV_BAR'
    if not field and any(key in row for key in ('epsActual', 'epsEstimate', 'earningsQuality')):
        field = 'EARNINGS_EVENT'
    period = str(row.get('periodEnd') or row.get('date') or '')[:10]
    return instrument, field, period, revision


def prepare(groups):
    """Return transient views; original hashes, receipts and rows remain owned upstream.

    Keys are compared across all lanes, including ordinary and research
    reactions which the engine can combine. Conservative fallback retains
    even identical duplicates, malformed records and unusual revisions.
    No raw observations or previous candidate graph are cached here.
    """
    if set(groups) != set(GROUPS):
        raise ValueError('comparison_input_groups_required')
    if any(not isinstance(groups[name], (list, tuple)) for name in GROUPS):
        return groups
    seen = set()
    for name in GROUPS:
        for row in groups[name]:
            if not isinstance(row, Mapping):
                return groups
            key = _revision_key(row)
            if key is None or key in seen:
                return groups
            seen.add(key)
    def research_view(row):
        if (row.get('instrumentId') != 'NIKKEI_225_INDEX'
                or row.get('availabilityBasis') != 'RESEARCH_KNOWN_AT_ENDPOINT_CLOSE'
                or row.get('derivationBasis') != 'DAILY_CLOSE_REFERENCE_NOT_INTRADAY_ATTRIBUTION'
                or row.get('eventTimeBasis') != 'ARCHIVED_RELEASE_DATE_FIXED_TIME_RULE'
                or row.get('status') != 'AVAILABLE'
                or row.get('historicalVintageVerified') is not False
                or row.get('actualPublicationTimeVerified') is not False
                or row.get('actionAuthority') is not False
                or any(not isinstance(row.get(key), str) or not _DIGEST.fullmatch(row[key])
                       for key in _BATCH_DIGESTS)):
            return row
        return {key: value for key, value in row.items() if key not in _BATCH_DIGESTS}
    return {**groups, 'research': [research_view(row) for row in groups['research']]}
