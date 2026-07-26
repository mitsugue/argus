export interface DataQualityIncident {
  id: string;
  severity: 'critical' | 'high' | 'medium';
  feature: string;
  impact: string;
  lastSuccess: string;
  currentState: string;
  nextRetry: string;
  ownerAction: string;
}

export interface DataQualityIncidentInput {
  sourceHealth: Array<{
    sourceName: string;
    status: string;
    freshnessBucket?: string;
    lastSuccessAt: string | null;
    ownerReadableStatusJa?: string;
    ownerReadableImpactJa: string;
    nextStepJa: string;
    nextRetryAt?: string | null;
    isExpectedDisabled: boolean;
  }>;
  scheduledMission?: {
    lastDelayClassification: string;
    lastScheduledTick: string | null;
    nextExpectedTick: string | null;
  };
  buildSoak?: {
    state?: string;
    status: string;
    lastHeartbeatAt?: string | null;
    blockerJa?: string | null;
  };
  remoteJournalVerification?: {
    readBackVerified: boolean;
    committedAt: string | null;
    readBackAt: string | null;
    pendingCount: number;
    errorClass: string | null;
  };
  publicLeakSafe: boolean;
}

const severityOf = (status: string): DataQualityIncident['severity'] =>
  /failed|critical|disabled_problem/i.test(status) ? 'critical'
    : /stale|degraded|warning/i.test(status) ? 'high' : 'medium';

export function buildDataQualityIncidents(input: DataQualityIncidentInput): DataQualityIncident[] {
  const incidents: DataQualityIncident[] = input.sourceHealth
    .filter((source) => {
      if (source.isExpectedDisabled) return false;
      const statusHealthy = ['ok', 'fresh', 'recent'].includes(source.status);
      const freshnessHealthy = !source.freshnessBucket
        || ['fresh', 'recent', 'unknown'].includes(source.freshnessBucket);
      return !(statusHealthy && freshnessHealthy);
    })
    .map((source) => {
      const currentState = source.freshnessBucket
        && ['stale', 'very_stale'].includes(source.freshnessBucket)
        ? `${source.status} / ${source.freshnessBucket}` : source.status;
      return {
        id: `source:${source.sourceName}`,
        severity: severityOf(currentState),
        feature: source.sourceName,
        impact: source.ownerReadableImpactJa || '影響範囲を確認中',
        lastSuccess: source.lastSuccessAt ?? '未記録',
        currentState: source.freshnessBucket
          && ['stale', 'very_stale'].includes(source.freshnessBucket)
          ? currentState : source.ownerReadableStatusJa
          ? `${source.ownerReadableStatusJa} (${currentState})` : currentState,
        nextRetry: source.nextRetryAt ?? '次回の自動更新',
        ownerAction: source.nextStepJa || '次回自動更新を確認',
      };
    });
  if (input.scheduledMission
    && !['on_time', 'unknown'].includes(input.scheduledMission.lastDelayClassification)) {
    incidents.push({
      id: 'scheduled-mission',
      severity: input.scheduledMission.lastDelayClassification === 'missed' ? 'critical' : 'high',
      feature: 'Scheduled Mission',
      impact: '定期更新と検証済みsnapshotが遅延',
      lastSuccess: input.scheduledMission.lastScheduledTick ?? '未記録',
      currentState: input.scheduledMission.lastDelayClassification,
      nextRetry: input.scheduledMission.nextExpectedTick ?? '未確定',
      ownerAction: '次の自然tickと重複executorを確認',
    });
  }
  if (input.buildSoak && ['verification_gap', 'interrupted'].includes(
    input.buildSoak.state ?? input.buildSoak.status)) {
    incidents.push({
      id: 'build-soak',
      severity: input.buildSoak.state === 'interrupted' ? 'critical' : 'high',
      feature: 'Build Soak',
      impact: input.buildSoak.blockerJa ?? '継続性証拠が未確認',
      lastSuccess: input.buildSoak.lastHeartbeatAt ?? '未記録',
      currentState: input.buildSoak.state ?? input.buildSoak.status,
      nextRetry: '次のscheduled heartbeat',
      ownerAction: '同一backend SHAのまま継続観測',
    });
  }
  if (input.remoteJournalVerification && !input.remoteJournalVerification.readBackVerified) {
    incidents.push({
      id: 'remote-journal',
      severity: input.remoteJournalVerification.errorClass ? 'high' : 'medium',
      feature: 'Remote Journal',
      impact: `read-back未確認 · pending ${input.remoteJournalVerification.pendingCount}`,
      lastSuccess: input.remoteJournalVerification.committedAt ?? '未記録',
      currentState: input.remoteJournalVerification.errorClass ?? 'verification_pending',
      nextRetry: '次のdurable read-back',
      ownerAction: 'receiptとoldest pending ageを確認',
    });
  }
  if (!input.publicLeakSafe) {
    incidents.unshift({
      id: 'privacy-guard',
      severity: 'critical',
      feature: 'Privacy Guard',
      impact: '公開レスポンスの漏洩安全性を証明できない',
      lastSuccess: '未確認',
      currentState: 'unsafe',
      nextRetry: '自動復旧なし',
      ownerAction: '公開利用を止め、redactionを確認',
    });
  }
  return incidents.sort((a, b) =>
    ({ critical: 0, high: 1, medium: 2 }[a.severity]
      - { critical: 0, high: 1, medium: 2 }[b.severity])
    || a.feature.localeCompare(b.feature));
}
