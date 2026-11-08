"""既存の入力更新を読む、固定工程だけの時間記録。取得や保存は起動しない。"""
from datetime import datetime, timezone
import math
import threading
import time

STAGES = frozenset((
    'pit_restore', 'pit_vix_nikkei', 'pit_fx_sp500', 'pit_macro_history',
    'pit_credit', 'pit_future_valuation', 'pit_level_map', 'pit_targets_internals',
    'pit_margin', 'pit_statements', 'pit_earnings', 'pit_vix_analog', 'pit_official',
    'pit_feature_history', 'pit_feature_sources', 'pit_feature_ledger',
    'pit_feature_reconcile', 'pit_feature_build', 'pit_feature_persist',
    'pit_research', 'pit_backup'))
MAX_FLIGHT_CALLS = 3


def _seconds(value):
    return round(value, 3) if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 86400 else None


def _stamp(value):
    if type(value) is str and len(value) <= 40:
        try:
            if datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None:
                return value
        except ValueError:
            pass
    return None


def _count(value):
    return value if type(value) is int and 0 <= value < 2**63 else None


def _flight_projection(value):
    row = value if isinstance(value, dict) else {}
    return {'callSequence': _count(row.get('callSequence')),
        'status': row.get('status') if row.get('status') in ('RUNNING', 'DONE', 'FAILED') else None,
        'mode': row.get('mode') if row.get('mode') in ('computed', 'joined', 'busy') else None,
        'startedAt': _stamp(row.get('startedAt')), 'finishedAt': _stamp(row.get('finishedAt')),
        'elapsedSeconds': _seconds(row.get('elapsedSeconds')),
        'preparationSequenceAtStart': _count(row.get('preparationSequenceAtStart')),
        'preparationSequenceAtEnd': _count(row.get('preparationSequenceAtEnd'))}


def projection(value):
    """非公開診断へ渡す項目を再限定する。工程中の他スレッドCPUは推計しない。"""
    row = value if isinstance(value, dict) else {}
    stages = row.get('completedStages')
    calls = row.get('flightCalls')
    return {'schemaVersion': 'argus-input-preparation-timing-v1',
        'status': row.get('status') if row.get('status') in ('NOT_STARTED', 'RUNNING', 'DONE', 'FAILED') else None,
        'sequence': row.get('sequence') if type(row.get('sequence')) is int and 0 <= row['sequence'] < 2**63 else None,
        'droppedStageCount': row.get('droppedStageCount') if type(row.get('droppedStageCount')) is int and 0 <= row['droppedStageCount'] < 2**63 else None,
        'startedAt': _stamp(row.get('startedAt')), 'finishedAt': _stamp(row.get('finishedAt')),
        'stage': row.get('stage') if type(row.get('stage')) is str and row['stage'] in STAGES else None,
        'stageStartedAt': _stamp(row.get('stageStartedAt')),
        'elapsedSeconds': _seconds(row.get('elapsedSeconds')),
        'cpuSeconds': _seconds(row.get('cpuSeconds')),
        'stageElapsedSeconds': _seconds(row.get('stageElapsedSeconds')),
        'completedStages': [{
            'stage': item['stage'], 'elapsedSeconds': _seconds(item.get('elapsedSeconds')),
            'cpuSeconds': _seconds(item.get('cpuSeconds'))}
            for item in (stages if isinstance(stages, list) else [])[-len(STAGES):]
            if isinstance(item, dict) and type(item.get('stage')) is str and item['stage'] in STAGES],
        'flightCalls': [_flight_projection(item) for item in
            (calls if isinstance(calls, list) else [])[-MAX_FLIGHT_CALLS:] if isinstance(item, dict)],
        'droppedFlightCallCount': _count(row.get('droppedFlightCallCount'))}


class InputPreparationTiming:
    """実行側の直近1回と、同じ更新を呼んだ直近3回を別々に計測。"""
    def __init__(self, *, clock=time.monotonic, cpu=time.thread_time, stamp=None):
        self._clock, self._cpu = clock, cpu
        self._stamp = stamp or (lambda: datetime.now(timezone.utc).isoformat())
        self._lock = threading.Lock()
        self._owner = None
        self._started = self._stage_started = self._cpu_started = self._stage_cpu = None
        self._row = {'status': 'NOT_STARTED', 'sequence': 0, 'completedStages': [], 'droppedStageCount': 0}
        self._flight_calls = []
        self._call_sequence = self._dropped_calls = 0

    def _cpu_now(self):
        try:
            return self._cpu()
        except (OSError, RuntimeError):
            return None

    @staticmethod
    def _delta(end, start):
        return max(0, end - start) if end is not None and start is not None else None

    def _close_stage(self, now, cpu):
        if self._stage_started is None:
            return
        self._row['completedStages'].append({
            'stage': self._row['stage'], 'elapsedSeconds': self._delta(now, self._stage_started),
            'cpuSeconds': self._delta(cpu, self._stage_cpu)})
        self._row['droppedStageCount'] += max(0, len(self._row['completedStages']) - len(STAGES))
        del self._row['completedStages'][:-len(STAGES)]

    def stage(self, name):
        if type(name) is not str or name not in STAGES:
            return
        with self._lock:
            if self._owner != threading.get_ident():
                return
            now, cpu = self._clock(), self._cpu_now()
            self._close_stage(now, cpu)
            self._stage_started, self._stage_cpu = now, cpu
            self._row.update(stage=name, stageStartedAt=self._stamp())

    def run(self, callback):
        with self._lock:
            observe = self._owner is None
            if observe:
                self._owner = threading.get_ident()
                self._started, self._cpu_started = self._clock(), self._cpu_now()
                self._stage_started = self._stage_cpu = None
                self._row = {'status': 'RUNNING', 'sequence': self._row['sequence'] + 1,
                    'startedAt': self._stamp(), 'finishedAt': None, 'completedStages': [], 'droppedStageCount': 0}
        if not observe:
            return callback()
        status = 'FAILED'
        try:
            result = callback()
            status = 'DONE'
            return result
        finally:
            with self._lock:
                now, cpu = self._clock(), self._cpu_now()
                self._close_stage(now, cpu)
                self._row.update(status=status, finishedAt=self._stamp(),
                    elapsedSeconds=self._delta(now, self._started),
                    cpuSeconds=self._delta(cpu, self._cpu_started),
                    stageElapsedSeconds=self._delta(now, self._stage_started))
                self._owner = None

    def observe_flight(self, dispatch, callback):
        """既存の返却modeを記録するだけ。待機期限・結果・例外を変えない。"""
        row = None
        try:
            with self._lock:
                started = self._clock()
                self._call_sequence += 1
                row = {'callSequence': self._call_sequence, 'status': 'RUNNING', 'mode': None,
                    'startedAt': self._stamp(), 'finishedAt': None,
                    'preparationSequenceAtStart': self._row['sequence']}
                self._flight_calls.append(row)
                self._dropped_calls += max(0, len(self._flight_calls) - MAX_FLIGHT_CALLS)
                del self._flight_calls[:-MAX_FLIGHT_CALLS]
        except Exception:
            row = None                         # 計時不能でも元の処理を実行する
        mode, status = None, 'FAILED'
        try:
            result, mode = dispatch(lambda: self.run(callback))
            status = 'DONE'
            return result, mode
        finally:
            if row is not None:
                try:
                    with self._lock:
                        row.update(status=status, mode=mode, finishedAt=self._stamp(),
                            elapsedSeconds=self._delta(self._clock(), started),
                            preparationSequenceAtEnd=self._row['sequence'])
                except Exception:
                    pass                       # 観測失敗で元の結果・例外を置換しない

    def view(self):
        with self._lock:
            row = dict(self._row)
            row.update(flightCalls=[dict(call) for call in self._flight_calls],
                       droppedFlightCallCount=self._dropped_calls)
            if self._owner is not None:
                now = self._clock()
                row.update(elapsedSeconds=self._delta(now, self._started), cpuSeconds=None,
                           stageElapsedSeconds=self._delta(now, self._stage_started))
            return projection(row)
