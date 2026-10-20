"""Immutable public market explanations and calculation inputs on persistent storage.

This store has no provider, order or portfolio access. Read paths cannot create
or repair files. Results append separately and never rewrite an issued view.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import tempfile
from datetime import datetime

from argus_product_naming import require_allowed
import argus_analysis_history_local as local_form

SCHEMA = 'argus-market-analysis-record-v1'
MAX_RECORD_BYTES = 2 * 1024 * 1024
BRIEF_FIELDS = ('schemaVersion', 'generatedAt', 'facts', 'chips', 'now', 'why', 'next',
    'aiText', 'aiModel', 'aiDiagnostics', 'unifiedContext', 'unifiedSummary',
    'unifiedStatus', 'lastSuccessfulAiAt', 'sdaAuthority', 'noteJa', 'hasCritical',
    'presentationCatalog', 'presentationPlan', 'presentationStatus', 'numericalResearch',
    'fiscalEnvironment', 'creditConditions', 'marketPosition', 'generationTrigger')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _instant(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('analysis_time_requires_timezone')
    return parsed


def make_record(brief, calculations):
    if brief.get('unifiedStatus') != 'GENERATED' or brief.get('sdaAuthority') is not False:
        raise ValueError('accepted_non_authoritative_explanation_required')
    context, summary = brief['unifiedContext'], brief['unifiedSummary']
    if context.get('ownerContextAvailable') is not False or summary.get('ownerContextAvailable') is not False:
        raise ValueError('public_history_cannot_contain_owner_context')
    if summary['contextId'] != context['contextId'] or summary.get('actionAuthority') is not False:
        raise ValueError('matching_non_authoritative_context_required')
    recorded_at = brief['aiDiagnostics']['completedAt']
    _instant(recorded_at)
    if (not isinstance(calculations, dict) or set(calculations) - {'1', '5', '10', '20'}
            or any(not isinstance(value, dict) for value in calculations.values())):
        raise ValueError('known_calculation_horizons_required')
    saved_brief = {k: brief[k] for k in BRIEF_FIELDS if k in brief}
    if 'marketPosition' in saved_brief:
        from argus_market_position_memory import public_snapshot
        saved_brief['marketPosition'] = public_snapshot(saved_brief['marketPosition'])
    body = {'schemaVersion': SCHEMA, 'recordedAt': recorded_at, 'scope': 'PUBLIC_MARKET',
            'brief': saved_brief,
            'calculations': calculations, 'actionAuthority': False,
            'inputSnapshotDigest': hashlib.sha256(_json({'context': context, 'calculations': calculations}).encode()).hexdigest()}
    require_allowed(body)
    encoded = _json(body).encode()
    if len(encoded) > MAX_RECORD_BYTES:
        raise ValueError('analysis_record_bound_exceeded')
    return {'recordId': hashlib.sha256(encoded).hexdigest(), **json.loads(encoded)}


def validate_record(value):
    if not isinstance(value, dict) or value.get('schemaVersion') != SCHEMA:
        raise ValueError('analysis_schema_invalid')
    rebuilt = make_record(value['brief'], value['calculations'])
    if rebuilt != value:
        raise ValueError('analysis_record_integrity_mismatch')
    return rebuilt


def _connect(path, readonly=False):
    path = Path(path)
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('analysis_history_regular_file_required')
    conn = sqlite3.connect(path.resolve().as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                           uri=True, timeout=15, isolation_level=None)
    # 1 = every body is the full record; 2 = some bodies are skeletons whose
    # calculation parts live in view_parts (2026-10-20). An older build only
    # accepts 1, so it refuses a converted file instead of misreading it.
    if conn.execute('PRAGMA user_version').fetchone()[0] not in (1, local_form.FORM_SCHEMA_VERSION):
        conn.close(); raise ValueError('analysis_history_schema_invalid')
    if not readonly:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('PRAGMA foreign_keys=ON')
    return conn


def initialize(path):
    path = Path(path)
    if path.exists() or path.is_symlink():
        _connect(path, True).close(); return
    fd, temporary = tempfile.mkstemp(prefix='.analysis-history-', dir=path.parent)
    os.close(fd)
    try:
        conn = sqlite3.connect(temporary, isolation_level=None)
        try:
            conn.executescript('''PRAGMA synchronous=FULL;
                BEGIN IMMEDIATE;
                CREATE TABLE views(sequence INTEGER PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
                  recorded_at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE outcomes(sequence INTEGER PRIMARY KEY, result_id TEXT NOT NULL UNIQUE,
                  record_id TEXT NOT NULL REFERENCES views(record_id), body TEXT NOT NULL);
                PRAGMA user_version=1; COMMIT;''')
        finally: conn.close()
        with open(temporary, 'rb') as handle: os.fsync(handle.fileno())
        try: os.link(temporary, path, follow_symlinks=False)
        except FileExistsError: _connect(path, True).close()
        directory = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally: os.unlink(temporary)


def append(path, record):
    record = validate_record(record); body = _json(record)
    conn = _connect(path)
    try:
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute('SELECT body FROM views WHERE record_id=?', (record['recordId'],)).fetchone()
        if existing and local_form.full_body(conn, record['recordId'], existing[0]) != body:
            raise ValueError('conflicting_analysis_record_id')
        if not existing:
            conn.execute('INSERT INTO views(record_id,recorded_at,body) VALUES(?,?,?)',
                         (record['recordId'], record['recordedAt'], body))
        conn.execute('COMMIT')
        return {'recordId': record['recordId'], 'inserted': not bool(existing), 'status': 'LOCAL_DURABLE'}
    except Exception:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
    finally: conn.close()


def read_record(path, record_id=None, *, presentation_only=False):
    if record_id is not None and not re.fullmatch('[a-f0-9]{64}', str(record_id)):
        raise ValueError('invalid_analysis_record_id')
    conn = _connect(path, True)
    try:
        row = (conn.execute('SELECT record_id,body FROM views WHERE record_id=?', (record_id,)).fetchone()
               if record_id else conn.execute('SELECT record_id,body FROM views '
                   + ("WHERE json_extract(body,'$.brief.presentationStatus')='GENERATED' " if presentation_only else '')
                   + 'ORDER BY julianday(recorded_at) DESC,sequence DESC LIMIT 1').fetchone())
        if not row: return None
        record = validate_record(json.loads(local_form.full_body(conn, row[0], row[1])))
        if record['recordId'] != row[0]: raise ValueError('analysis_index_integrity_mismatch')
        return record
    finally: conn.close()


def summary(path):
    """Row counts and the latest view id without reading any record body."""
    conn = _connect(path, True)
    try:
        views = conn.execute('SELECT COUNT(*) FROM views').fetchone()[0]
        outcomes = conn.execute('SELECT COUNT(*) FROM outcomes').fetchone()[0]
        latest = conn.execute('SELECT record_id FROM views ORDER BY julianday(recorded_at) DESC,sequence DESC LIMIT 1').fetchone()
        return {'counts': {'views': int(views), 'outcomes': int(outcomes)},
                'latestRecordId': latest[0] if latest else None}
    finally: conn.close()


CALL_REPORT_MAX_DAYS = 45
# Each read is one short statement: the history uses a rollback journal, so a
# long read would hold the shared lock and delay the next saved view.
CALL_REPORT_PAGE_ROWS = 20
CALL_REPORT_MAX_ROWS = 5000


def _count(value):
    """A non-negative integer count, or None (a bool or a text is not a count)."""
    return value if type(value) is int and value >= 0 else None


def call_report(path, *, since_day):
    """Per-UTC-day call counts of the saved views; no prices, no record text.

    2026-10-16 (owner): measure whether the 13.8.91 reduction lowered the
    correction calls, in counts, ratios and tokens only. SQLite reads only the
    diagnostics object of each record, once per record, in pages of short
    statements. Only views that were saved are counted; a generation that
    failed validation and was never saved is not here.
    """
    from datetime import date as _date
    day = _date.fromisoformat(str(since_day))
    rows, after, truncated = [], 0, False
    while True:
        conn = _connect(path, True)
        try:
            page = conn.execute(
                # One parse per record: the three paths come back as one array.
                "SELECT sequence, substr(recorded_at,1,10),"
                " json_extract(body,'$.brief.aiDiagnostics','$.brief.generationTrigger','$.brief.aiText.nowJa')"
                " FROM views WHERE sequence > ? AND recorded_at >= ? ORDER BY sequence LIMIT ?",
                (after, day.isoformat(), CALL_REPORT_PAGE_ROWS)).fetchall()
        finally:
            conn.close()
        if not page:
            break
        rows.extend(page)
        after = page[-1][0]
        if len(rows) >= CALL_REPORT_MAX_ROWS:
            truncated = True
            break
    days = {}
    previous_conclusion = None
    for _sequence, key, extracted in rows:
        row = days.setdefault(key, {
            "dayUtc": key, "views": 0, "viewsWithAi": 0, "viewsWithCorrection": 0,
            "aiCalls": 0, "correctionCalls": 0, "firstRejectionReasons": {},
            "inputTokens": 0, "outputTokens": 0, "cachedInputTokens": 0, "unknownTokenAttempts": 0,
            "conclusionChanged": 0, "triggers": {}, "changedFactGroups": {}})
        row["views"] += 1
        try:
            values = json.loads(extracted) if extracted else []
        except ValueError:
            values = []
        values = values if isinstance(values, list) and len(values) == 3 else [None, None, None]
        diagnostics, trigger, conclusion = values
        # 2026-10-17 (owner): how often the written conclusion actually moves,
        # between consecutive saved editions (older records included).
        if isinstance(conclusion, str):
            if previous_conclusion is not None and conclusion != previous_conclusion:
                row["conclusionChanged"] += 1
            previous_conclusion = conclusion
        trigger = trigger if isinstance(trigger, dict) else {}
        kind = re.sub(r"[^A-Z_]", "_", str(trigger.get("kind") or "NOT_RECORDED"))[:20]
        row["triggers"][kind] = row["triggers"].get(kind, 0) + 1
        for group in trigger.get("changedFactGroups") or []:
            name = re.sub(r"[^a-z_]", "_", str(group))[:30]
            row["changedFactGroups"][name] = row["changedFactGroups"].get(name, 0) + 1
        diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
        attempts = diagnostics.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            continue
        row["viewsWithAi"] += 1
        row["aiCalls"] += len(attempts)
        reduction = diagnostics.get("callReduction")
        corrections = _count(reduction.get("correctionCalls")) if isinstance(reduction, dict) else None
        extra = corrections if corrections is not None else len(attempts) - 1
        row["correctionCalls"] += max(0, extra)
        if extra > 0:
            first = (attempts[0].get("validation") or {}) if isinstance(attempts[0], dict) else {}
            first = first if isinstance(first, dict) else {}
            row["viewsWithCorrection"] += 1
            reason = re.sub(r"[^A-Za-z0-9_:.-]", "_", str(first.get("reason") or first.get("status") or "unknown"))[:60]
            if reason == "presentation_invalid" and first.get("detail"):
                # 2026-10-17: which presentation rule fails (a code such as
                # presentation_evidence_invalid), to target the next reduction.
                reason += ":" + re.sub(r"[^A-Za-z0-9_.-]", "_", str(first.get("detail")))[:60]
            row["firstRejectionReasons"][reason] = row["firstRejectionReasons"].get(reason, 0) + 1
        for attempt in attempts:
            provider = (attempt.get("provider") or {}) if isinstance(attempt, dict) else {}
            provider = provider if isinstance(provider, dict) else {}
            inp, out, cached = (_count(provider.get(k)) for k in ("inputTokens", "outputTokens", "cachedInputTokens"))
            if inp is None or out is None:
                row["unknownTokenAttempts"] += 1
                continue
            row["inputTokens"] += inp
            row["outputTokens"] += out
            row["cachedInputTokens"] += cached or 0
    return {"schemaVersion": "argus-brief-call-report-v3", "sinceDayUtc": day.isoformat(),
            "coverage": "saved_views_only", "rowsRead": len(rows), "truncated": truncated,
            "days": [days[k] for k in sorted(days)]}


def read_page_index(path, *, before_sequence=None, limit=20):
    """Sequence and record id only, newest first; no body leaves the database."""
    if type(limit) is not int or not 1 <= limit <= 100 or (before_sequence is not None and
            (type(before_sequence) is not int or before_sequence < 1)):
        raise ValueError('invalid_analysis_history_cursor')
    conn = _connect(path, True)
    try:
        rows = conn.execute('SELECT sequence,record_id FROM views WHERE sequence<? ORDER BY sequence DESC LIMIT ?',
                            (before_sequence if before_sequence is not None else 9223372036854775807, limit + 1)).fetchall()
        entries = [{'sequence': seq, 'recordId': identity} for seq, identity in rows[:limit]]
        return {'rows': entries, 'hasMore': len(rows) > limit,
                'nextBeforeSequence': entries[-1]['sequence'] if entries else None}
    finally: conn.close()


def read_page(path, *, before_sequence=None, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100 or (before_sequence is not None and
            (type(before_sequence) is not int or before_sequence < 1)):
        raise ValueError('invalid_analysis_history_cursor')
    conn = _connect(path, True)
    try:
        rows = conn.execute('SELECT sequence,record_id,body FROM views WHERE sequence<? ORDER BY sequence DESC LIMIT ?',
                            (before_sequence if before_sequence is not None else 9223372036854775807, limit + 1)).fetchall()
        entries = []
        for seq, identity, body in rows[:limit]:
            record = validate_record(json.loads(local_form.full_body(conn, identity, body)))
            if record['recordId'] != identity: raise ValueError('analysis_index_integrity_mismatch')
            entries.append({'sequence': seq, 'recordId': identity, 'recordedAt': record['recordedAt'],
                'inputSnapshotDigest': record['inputSnapshotDigest'],
                'contextId': record['brief']['unifiedContext']['contextId'],
                'sections': record['brief']['unifiedSummary']['sections'],
                'requestedModel': record['brief']['aiDiagnostics'].get('requestedModel'),
                'returnedModel': record['brief']['aiDiagnostics'].get('returnedModel'),
                'calculationHorizons': sorted(record['calculations'])})
        return {'status': 'AVAILABLE', 'scope': 'PUBLIC_MARKET', 'rows': entries,
                'hasMore': len(rows) > limit, 'nextBeforeSequence': entries[-1]['sequence'] if entries else None,
                'storage': 'PERSISTENT_ROOT_SQLITE', 'remoteRecoveryVerified': False,
                'readOnly': True, 'actionAuthority': False}
    finally: conn.close()


def outcome_candidates(record, price_rows, *, received_at):
    """Compare saved N225 paths with later completed cash-index sessions only."""
    from datetime import date, timedelta
    import math
    import argus_market_clock as clock
    record = validate_record(record)
    received = _instant(received_at)
    issued = _instant(record['recordedAt'])
    if received < issued: return []
    outcomes = []
    for key, calculation in record['calculations'].items():
        chart = calculation.get('comparison') or {}
        forecast = chart.get('forecast') or {}
        if chart.get('schemaVersion') != 'jp-market-comparison-v1' or forecast.get('horizonSessions') != int(key):
            continue
        target = date.fromisoformat(chart['anchorDate']); remaining = int(key)
        try:
            while remaining:
                target += timedelta(days=1)
                if clock.canonical_trading_day(clock.JP_EQUITY, target): remaining -= 1
        except clock.CalendarUnavailableError:
            continue
        close_at = clock.market_session_bounds(clock.JP_EQUITY, target)['regularCloseUtc']
        if not close_at or _instant(close_at) <= issued or _instant(close_at) > received:
            continue
        matched = [row for row in price_rows if row.get('date') == target.isoformat()]
        if len(matched) != 1: continue
        price = matched[0].get('close')
        anchor = chart.get('actualAnchorPrice')
        if not all(type(v) in (int,float) and math.isfinite(v) and v > 0 for v in (price,anchor)):
            continue
        last = [p for p in forecast.get('line',[]) if p.get('offsetSessions') == int(key)]
        if len(last) != 1 or chart.get('unit') not in ('ANCHOR_100','JPY_INDEX_POINTS'): continue
        predicted = last[0]['value'] * anchor / 100 if chart['unit'] == 'ANCHOR_100' else last[0]['value']
        if type(predicted) not in (int,float) or not math.isfinite(predicted) or predicted <= 0: continue
        threshold = forecast.get('flatThresholdPct')
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or threshold < 0: continue
        compared_actual = price / anchor * 100 if chart['unit'] == 'ANCHOR_100' else price
        change = (price / anchor - 1) * 100
        body = {'schemaVersion':'argus-analysis-outcome-v1','recordId':record['recordId'],
            'instrumentId':'NIKKEI_225_INDEX','horizonSessions':int(key),'targetDate':target.isoformat(),
            'actualClose':price,'actualChangePct':change,
            'forecastValue':last[0]['value'],'actualComparisonValue':compared_actual,'comparisonUnit':chart['unit'],
            'absoluteErrorPct':abs(predicted-price)/price*100,
            'flatThresholdPct':threshold,'actualClass':'up' if change>threshold else 'down' if change < -threshold else 'flat',
            'source':'Yahoo Finance cash index daily close','sourceCloseAt':close_at,
            'engineValidationStatus':forecast.get('validationStatus'),'predictiveProbabilityVerified':False,
            'actionAuthority':False}
        identity = hashlib.sha256(_json(body).encode()).hexdigest()
        body.update(resultId=identity,receivedAt=received_at)
        body['resultDigest'] = hashlib.sha256(_json(body).encode()).hexdigest()
        outcomes.append(body)
    return outcomes


def append_outcomes(path, values):
    values = list(values)
    if len(values)>400: raise ValueError('analysis_outcome_batch_bound')
    conn=_connect(path)
    try:
        conn.execute('BEGIN IMMEDIATE'); inserted=0
        for row in values:
            body=dict(row);digest=body.pop('resultDigest')
            if hashlib.sha256(_json(body).encode()).hexdigest()!=digest: raise ValueError('analysis_outcome_integrity')
            require_allowed(row)
            previous=conn.execute('SELECT body FROM outcomes WHERE result_id=?',(row['resultId'],)).fetchone()
            if previous:
                prior=json.loads(previous[0])
                if {k:v for k,v in prior.items() if k not in ('receivedAt','resultDigest')} != {k:v for k,v in row.items() if k not in ('receivedAt','resultDigest')}:
                    raise ValueError('analysis_outcome_identity_conflict')
                continue
            conn.execute('INSERT INTO outcomes(result_id,record_id,body) VALUES(?,?,?)',(row['resultId'],row['recordId'],_json(row)));inserted+=1
        conn.execute('COMMIT'); return inserted
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()


def read_outcomes(path, record_id):
    conn=_connect(path,True)
    try:
        values=[]
        for (body,) in conn.execute('SELECT body FROM outcomes WHERE record_id=? ORDER BY sequence',(record_id,)):
            row=json.loads(body);check=dict(row);digest=check.pop('resultDigest')
            if hashlib.sha256(_json(check).encode()).hexdigest()!=digest:raise ValueError('analysis_outcome_integrity')
            values.append(row)
        return values
    finally:conn.close()


TRACK_RECORD_MINIMUM = 20


def _wilson_lower(hits, total, z=1.959963984540054):
    import math
    if total <= 0: return None
    p = hits / total; centre = p + z * z / (2 * total)
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - margin) / (1 + z * z / total)


def track_record(path):
    """Direction record of the Nikkei paths this product actually issued.

    One forecast per (horizon, anchor session): the earliest view issued before
    the first session of its horizon opened, so no counted forecast saw any of
    the move it is scored on. The latest appended result for that view is used
    (a corrected close replaces the first reading). Frequencies of past issued
    forecasts, never a probability for the next one.
    """
    from datetime import date, timedelta
    import argus_market_clock as clock
    conn = _connect(path, True)
    try:
        rows = conn.execute('SELECT o.body, v.recorded_at FROM outcomes o JOIN views v ON o.record_id=v.record_id '
                            'ORDER BY julianday(v.recorded_at), v.sequence, o.sequence').fetchall()
    finally: conn.close()
    chosen = {}
    for body, recorded_at in rows:
        row = json.loads(body)
        horizon, target = row.get('horizonSessions'), row.get('targetDate')
        if horizon not in (1, 5, 10, 20) or not isinstance(target, str): continue
        key = (horizon, target)
        if key in chosen and chosen[key]['recordId'] != row['recordId']: continue
        first = date.fromisoformat(target); remaining = horizon - 1
        try:
            while remaining:
                first -= timedelta(days=1)
                if clock.canonical_trading_day(clock.JP_EQUITY, first): remaining -= 1
            opened = clock.market_session_bounds(clock.JP_EQUITY, first)['regularOpenUtc']
        except clock.CalendarUnavailableError:
            continue
        if not opened or _instant(recorded_at) >= _instant(opened): continue
        chosen[key] = row
    horizons = {}
    for horizon in (1, 5, 10, 20):
        hits = up = down = directional = 0; dates = []
        for (h, target), row in sorted(chosen.items()):
            if h != horizon: continue
            threshold, value = row['flatThresholdPct'], row['forecastValue']
            if row['comparisonUnit'] == 'ANCHOR_100':
                predicted_change = value - 100
            else:
                anchor = row['actualClose'] / (1 + row['actualChangePct'] / 100)
                predicted_change = (value / anchor - 1) * 100
            predicted = 'up' if predicted_change > threshold else 'down' if predicted_change < -threshold else 'flat'
            dates.append(target)
            if predicted == 'flat': continue
            directional += 1; hits += row['actualClass'] == predicted
            up += row['actualClass'] == 'up'; down += row['actualClass'] == 'down'
        rate = hits / directional if directional else None
        naive = max(up, down) / directional if directional else None
        lower = _wilson_lower(hits, directional)
        status = ('INSUFFICIENT_SAMPLE' if directional < TRACK_RECORD_MINIMUM
                  else 'ABOVE_BASELINE' if lower is not None and lower > naive else 'NOT_ABOVE_BASELINE')
        horizons[str(horizon)] = {'horizonSessions': horizon, 'scoredForecasts': len(dates),
            'directionalForecasts': directional, 'hits': hits, 'hitRate': rate,
            'hitRateWilsonLower95': lower, 'naiveMajorityRate': naive, 'status': status,
            'firstTargetDate': dates[0] if dates else None, 'lastTargetDate': dates[-1] if dates else None}
    return {'schemaVersion': 'argus-forecast-track-record-v1', 'instrumentId': 'NIKKEI_225_INDEX',
            'minimumDirectionalForecasts': TRACK_RECORD_MINIMUM, 'horizons': horizons,
            'predictiveProbabilities': None, 'actionAuthority': False}


# --- Nikkei morning level map (2026-10-04) ---------------------------------------
# Two append-only tables in the same file: the daily ARGUS EPS estimate and the
# map fixed before each open. The first body stored for a date is kept; a later
# different body for the same date is refused and reported, never written. The
# views/outcomes tables and their remote backup are not changed: these tables
# are local-durable only until the backup carries them (documented).
_LEVEL_MAP_TABLES = '''CREATE TABLE IF NOT EXISTS level_map_eps(session TEXT PRIMARY KEY,
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS level_map_mornings(morning_of TEXT PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
      created_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS candidate_records(record_key TEXT PRIMARY KEY, record_id TEXT NOT NULL UNIQUE,
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS future_map_versions(record_id TEXT PRIMARY KEY,
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS future_map_outcomes(outcome_id TEXT PRIMARY KEY,
      record_id TEXT NOT NULL REFERENCES future_map_versions(record_id),
      recorded_at TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS level_map_eps_corrections(correction_id TEXT PRIMARY KEY,
      session TEXT NOT NULL, recorded_at TEXT NOT NULL, original_sha256 TEXT NOT NULL, body TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS level_map_morning_corrections(correction_id TEXT PRIMARY KEY,
      morning_of TEXT NOT NULL, created_at TEXT NOT NULL, original_sha256 TEXT NOT NULL, body TEXT NOT NULL);'''


def _append_once(path, table, key_column, key, values):
    conn = _connect(path)
    try:
        conn.executescript(_LEVEL_MAP_TABLES)
        conn.execute('BEGIN IMMEDIATE')
        existing = conn.execute(f'SELECT body FROM {table} WHERE {key_column}=?', (key,)).fetchone()
        body = values[-1]
        if existing:
            conn.execute('COMMIT')
            return {'inserted': False, 'conflict': existing[0] != body}
        marks = ','.join('?' * len(values))
        conn.execute(f'INSERT INTO {table} VALUES({marks})', values)
        conn.execute('COMMIT')
        return {'inserted': True, 'conflict': False}
    except Exception:
        if conn.in_transaction: conn.execute('ROLLBACK')
        raise
    finally: conn.close()


def append_level_map_eps(path, record):
    session = str(record.get('date') or '')
    datetime.fromisoformat(session)
    return _append_once(path, 'level_map_eps', 'session', session,
                        (session, str(record.get('recordedAt') or ''), _json(record)))


def append_level_map_eps_correction(path, record):
    """Append a complete replacement for a known partial input, keep its original.

    This never changes a morning map or a valid first estimate. The receipt
    ordering and original digest are part of the immutable correction.
    """
    import jp_market_level_map as levels
    session = str(record.get('date') or '')
    datetime.fromisoformat(session)
    received = _instant(str(record.get('recordedAt') or ''))
    if record.get('basis') != levels.EPS_BASIS or not levels.estimate_input_usable(record, strict=True):
        raise ValueError('level_map_eps_complete_correction_required')
    conn = _connect(path)
    try:
        conn.executescript(_LEVEL_MAP_TABLES);conn.execute('BEGIN IMMEDIATE')
        old = conn.execute('SELECT body FROM level_map_eps WHERE session=?',(session,)).fetchone()
        if old is None or levels.estimate_input_usable(json.loads(old[0])):
            raise ValueError('level_map_eps_incomplete_original_required')
        original = json.loads(old[0])
        if original.get('basis') != record.get('basis') or received <= _instant(original['recordedAt']):
            raise ValueError('level_map_eps_correction_receipt_order')
        digest = hashlib.sha256(old[0].encode()).hexdigest();body = _json(record)
        identity = hashlib.sha256(_json([session,digest,record]).encode()).hexdigest()
        inserted = conn.execute('INSERT OR IGNORE INTO level_map_eps_corrections VALUES(?,?,?,?,?)',
            (identity,session,record['recordedAt'],digest,body)).rowcount
        conn.execute('COMMIT')
        return {'inserted':bool(inserted),'conflict':False,'correctionId':identity}
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()


def append_level_map_morning_correction(path, record):
    """Correct only a known partial future morning, before its market open."""
    import jp_market_level_map as levels
    day=str(record.get('morningOf') or '');datetime.fromisoformat(day)
    created=_instant(str(record.get('createdAt') or ''))
    if (not str(record.get('recordId') or '').startswith('lm-')
            or not levels.estimate_input_usable({'coverage':record.get('epsCoverage')},strict=True)
            or created >= _instant(day+'T00:00:00Z')):
        raise ValueError('level_map_complete_preopen_correction_required')
    conn=_connect(path)
    try:
        conn.executescript(_LEVEL_MAP_TABLES);conn.execute('BEGIN IMMEDIATE')
        old=conn.execute('SELECT body FROM level_map_mornings WHERE morning_of=?',(day,)).fetchone()
        if old is None or levels.morning_input_usable(json.loads(old[0])):
            raise ValueError('level_map_incomplete_original_required')
        original=json.loads(old[0])
        if (original.get('epsBasis')!=record.get('epsBasis')
                or created <= _instant(original['createdAt'])):
            raise ValueError('level_map_correction_receipt_order')
        digest=hashlib.sha256(old[0].encode()).hexdigest();body=_json(record)
        identity=hashlib.sha256(_json([day,digest,record]).encode()).hexdigest()
        inserted=conn.execute('INSERT OR IGNORE INTO level_map_morning_corrections VALUES(?,?,?,?,?)',
            (identity,day,record['createdAt'],digest,body)).rowcount
        conn.execute('COMMIT')
        return {'inserted':bool(inserted),'conflict':False,'correctionId':identity}
    except Exception:
        if conn.in_transaction:conn.execute('ROLLBACK')
        raise
    finally:conn.close()


def read_level_map_eps_originals(path, *, morning=False):
    conn = _connect(path, True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table,column=('level_map_mornings','morning_of') if morning else ('level_map_eps','session')
        correction_table='level_map_morning_corrections' if morning else 'level_map_eps_corrections'
        originals = {r[0]:json.loads(r[1]) for r in conn.execute(f'SELECT {column},body FROM {table} ORDER BY {column}')} if table in names else {}
        corrections = [{'correctionId':r[0],'date':r[1],'recordedAt':r[2],'originalSha256':r[3],'record':json.loads(r[4])}
            for r in conn.execute(f'SELECT * FROM {correction_table} ORDER BY {column},'+('created_at' if morning else 'recorded_at')+',correction_id')] if correction_table in names else []
        return originals,corrections
    finally:conn.close()


def append_level_map(path, record):
    morning = str(record.get('morningOf') or '')
    datetime.fromisoformat(morning)
    if not str(record.get('recordId') or '').startswith('lm-'):
        raise ValueError('level_map_record_id_required')
    return _append_once(path, 'level_map_mornings', 'morning_of', morning,
                        (morning, record['recordId'], str(record.get('createdAt') or ''), _json(record)))


def read_level_map_state(path):
    """Every stored estimate (by session) and every stored morning map, oldest first."""
    conn = _connect(path, True)
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        eps = {}
        if 'level_map_eps' in names:
            eps = {row[0]: json.loads(row[1]) for row in conn.execute(
                'SELECT session, body FROM level_map_eps ORDER BY session')}
        if 'level_map_eps_corrections' in names:
            for session,body in sorted(conn.execute('SELECT session,body FROM level_map_eps_corrections'),key=lambda row:_instant(json.loads(row[1])['recordedAt'])):
                eps[session]=json.loads(body)
        mornings = []
        if 'level_map_mornings' in names:
            mornings = [json.loads(row[0]) for row in conn.execute(
                'SELECT body FROM level_map_mornings ORDER BY morning_of')]
        if 'level_map_morning_corrections' in names:
            corrected={m['morningOf']:m for m in mornings}
            for body, in sorted(conn.execute('SELECT body FROM level_map_morning_corrections'),key=lambda row:_instant(json.loads(row[0])['createdAt'])):
                row=json.loads(body);corrected[row['morningOf']]=row
            mornings=[corrected[day] for day in sorted(corrected)]
        return {'eps': eps, 'mornings': mornings}
    finally: conn.close()


# Pre-registered candidate signals (2026-10-04): one record per candidate and
# signal day, first body kept, same file and same rules as the level map.
def append_candidate_record(path, record):
    candidate, day = str(record.get('candidate') or ''), str(record.get('signalDate') or '')
    datetime.fromisoformat(day)
    if not candidate or not str(record.get('recordId') or '').startswith('cr-'):
        raise ValueError('candidate_record_identity_required')
    return _append_once(path, 'candidate_records', 'record_key', f'{candidate}:{day}',
                        (f'{candidate}:{day}', record['recordId'], str(record.get('recordedAt') or ''), _json(record)))


def read_candidate_records(path):
    conn = _connect(path, True)
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'candidate_records' not in names:
            return []
        return [json.loads(row[0]) for row in conn.execute('SELECT body FROM candidate_records ORDER BY record_key')]
    finally: conn.close()


def _validate_future_map_version(record):
    from argus_future_map_scoring import registration
    if registration(record['row'], received_at=record['recordedAt']) != record:
        raise ValueError('future_map_registration_integrity')
    require_allowed(record)


def append_future_map_version(path, record):
    _validate_future_map_version(record)
    return _append_once(path, 'future_map_versions', 'record_id', record['recordId'],
                        (record['recordId'], record['recordedAt'], _json(record)))


def _validate_future_map_outcome(outcome):
    from argus_future_map_scoring import digest, instant, METHOD
    instant(outcome['scoredAt'])
    body = {key: value for key, value in outcome.items() if key not in ('scoredAt', 'outcomeId')}
    if (outcome.get('schemaVersion') != METHOD or outcome.get('status') != 'SCORED'
            or outcome.get('result') not in ('reached', 'missed')
            or outcome.get('actionAuthority') is not False
            or outcome.get('turningPointValidated') is not False
            or outcome.get('probability') is not None
            or outcome.get('outcomeId') != 'fmo-' + digest(body)):
        raise ValueError('future_map_outcome_integrity')
    require_allowed(outcome)


def append_future_map_outcome(path, outcome):
    _validate_future_map_outcome(outcome)
    return _append_once(path, 'future_map_outcomes', 'outcome_id', outcome['outcomeId'],
                        (outcome['outcomeId'], outcome['recordId'], outcome['scoredAt'], _json(outcome)))


def read_future_map_state(path):
    conn = _connect(path, True)
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = ([json.loads(row[0]) for row in conn.execute(
            'SELECT body FROM future_map_versions ORDER BY recorded_at, rowid')]
            if 'future_map_versions' in names else [])
        outcomes = ([json.loads(row[0]) for row in conn.execute(
            'SELECT body FROM future_map_outcomes ORDER BY rowid')]
            if 'future_map_outcomes' in names else [])
        for record in versions:
            _validate_future_map_version(record)
        ids = {record['recordId'] for record in versions}
        for outcome in outcomes:
            _validate_future_map_outcome(outcome)
            if outcome['recordId'] not in ids:
                raise ValueError('future_map_outcome_registration_missing')
        return {'versions': versions, 'outcomes': outcomes}
    finally: conn.close()


# ── Local form (2026-10-20 owner decision) ──────────────────────────────────
FORM_BATCH_LIMIT = 48


def read_full_body(path, table, column, identity):
    """One short read of one row's original body (views rebuilt from parts)."""
    if table not in ('views', 'outcomes') or column not in ('record_id', 'result_id'):
        raise ValueError('analysis_history_table_invalid')
    conn = _connect(path, True)
    try:
        rows = conn.execute(f'SELECT body FROM {table} WHERE {column}=?', (identity,)).fetchall()
        if len(rows) != 1:
            return None
        return local_form.full_body(conn, identity, rows[0][0]) if table == 'views' else rows[0][0]
    finally: conn.close()


def form_status(path):
    """Counts and bytes of both forms; reads no record body."""
    conn = _connect(path, True)
    try:
        views = conn.execute('SELECT COUNT(*) FROM views').fetchone()[0]
        out = {'views': int(views), 'migrated': 0, 'remaining': int(views), 'partCount': 0,
               'partStoredBytes': 0, 'fullBytesMigrated': 0, 'skeletonBytes': 0,
               'userVersion': conn.execute('PRAGMA user_version').fetchone()[0]}
        if local_form.tables_present(conn):
            migrated, full_bytes, skeleton_bytes = conn.execute(
                'SELECT COUNT(*), COALESCE(SUM(full_bytes),0), COALESCE(SUM(skeleton_bytes),0) FROM form_migrations').fetchone()
            parts, stored = conn.execute('SELECT COUNT(*), COALESCE(SUM(length(body)),0) FROM view_parts').fetchone()
            out.update(migrated=int(migrated), remaining=int(views) - int(migrated), partCount=int(parts),
                       partStoredBytes=int(stored), fullBytesMigrated=int(full_bytes),
                       skeletonBytes=int(skeleton_bytes))
        return out
    finally: conn.close()


def migrate_to_parts(path, *, now_iso, limit=FORM_BATCH_LIMIT):
    """Move up to `limit` full rows into the local form, one short transaction each.

    A row is replaced only after its skeleton and stored parts rebuild the
    original body byte for byte; otherwise it stays full and is reported."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('analysis_history_form_limit')
    conn = _connect(path)
    result = {'migrated': 0, 'unchanged': 0, 'partsAdded': 0, 'partBytesAdded': 0, 'failures': []}
    try:
        if not local_form.tables_present(conn):
            conn.executescript('BEGIN IMMEDIATE;' + local_form.TABLES + 'COMMIT;')
        ids = [r[0] for r in conn.execute(
            'SELECT record_id FROM views WHERE record_id NOT IN (SELECT record_id FROM form_migrations) '
            'ORDER BY sequence LIMIT ?', (limit,))]
        for record_id in ids:
            conn.execute('BEGIN IMMEDIATE')
            try:
                row = conn.execute('SELECT body FROM views WHERE record_id=?', (record_id,)).fetchone()
                done = conn.execute('SELECT 1 FROM form_migrations WHERE record_id=?', (record_id,)).fetchone()
                if not row or done:
                    conn.execute('COMMIT'); continue
                body = row[0]
                record = validate_record(json.loads(body))
                if _json(record) != body:
                    raise ValueError('analysis_history_body_not_canonical')
                skeleton, parts = local_form.split(record)
                if not parts:
                    result['unchanged'] += 1
                for identity, raw in sorted(parts.items()):
                    added = local_form.store_part(conn, identity, raw)
                    if added:
                        result['partsAdded'] += 1; result['partBytesAdded'] += added
                skeleton_body = local_form.canonical(skeleton)
                rebuilt = local_form.canonical(local_form.assemble(
                    json.loads(skeleton_body), lambda identity: local_form.read_part(conn, identity)))
                if rebuilt != body:
                    raise ValueError('analysis_history_rebuild_mismatch')
                encoded = body.encode()
                conn.execute('INSERT INTO form_migrations(record_id,full_sha256,full_bytes,skeleton_bytes,migrated_at) '
                             'VALUES(?,?,?,?,?)', (record_id, local_form.digest(encoded), len(encoded),
                                                   len(skeleton_body.encode()), now_iso))
                updated = conn.execute('UPDATE views SET body=? WHERE record_id=? AND body=?',
                                       (skeleton_body, record_id, body)).rowcount
                if updated != 1:
                    raise ValueError('analysis_history_row_changed')
                if conn.execute('PRAGMA user_version').fetchone()[0] != local_form.FORM_SCHEMA_VERSION:
                    conn.execute(f'PRAGMA user_version={local_form.FORM_SCHEMA_VERSION}')
                conn.execute('COMMIT')
                result['migrated'] += 1
            except Exception as exc:
                if conn.in_transaction: conn.execute('ROLLBACK')
                result['failures'].append({'recordId': record_id, 'reason': str(exc)[:80]})
        return result
    finally: conn.close()


def restore_full_bodies(path, *, limit=FORM_BATCH_LIMIT):
    """Write rebuilt original bodies back (the way back); verified by the recorded SHA-256."""
    conn = _connect(path)
    restored = 0
    try:
        if not local_form.tables_present(conn):
            return {'restored': 0, 'remaining': 0}
        ids = [r[0] for r in conn.execute('SELECT record_id FROM form_migrations LIMIT ?', (limit,))]
        for record_id in ids:
            conn.execute('BEGIN IMMEDIATE')
            try:
                body = conn.execute('SELECT body FROM views WHERE record_id=?', (record_id,)).fetchone()[0]
                full = local_form.full_body(conn, record_id, body)
                conn.execute('UPDATE views SET body=? WHERE record_id=? AND body=?', (full, record_id, body))
                conn.execute('DELETE FROM form_migrations WHERE record_id=?', (record_id,))
                if not conn.execute('SELECT COUNT(*) FROM form_migrations').fetchone()[0]:
                    conn.execute('PRAGMA user_version=1')
                conn.execute('COMMIT')
                restored += 1
            except Exception:
                if conn.in_transaction: conn.execute('ROLLBACK')
                raise
        remaining = conn.execute('SELECT COUNT(*) FROM form_migrations').fetchone()[0]
        return {'restored': restored, 'remaining': int(remaining)}
    finally: conn.close()


def verify_all_bodies(path):
    """Rebuild every converted row and check it against its recorded SHA-256."""
    conn = _connect(path, True)
    try:
        if not local_form.tables_present(conn):
            return {'checked': 0, 'mismatches': 0}
        ids = [r[0] for r in conn.execute('SELECT record_id FROM form_migrations ORDER BY record_id')]
    finally: conn.close()
    mismatches = 0
    for record_id in ids:
        try:
            read_full_body(path, 'views', 'record_id', record_id)
        except ValueError:
            mismatches += 1
    return {'checked': len(ids), 'mismatches': mismatches}


def free_page_bytes(path):
    conn = _connect(path, True)
    try:
        return int(conn.execute('PRAGMA freelist_count').fetchone()[0]) * int(conn.execute('PRAGMA page_size').fetchone()[0])
    finally: conn.close()


def compact_file(path):
    """Return freed pages to the filesystem once every row is converted (VACUUM)."""
    conn = _connect(path)
    try:
        before = Path(path).stat().st_size
        conn.execute('VACUUM')
        return {'beforeBytes': before, 'afterBytes': Path(path).stat().st_size}
    finally: conn.close()
