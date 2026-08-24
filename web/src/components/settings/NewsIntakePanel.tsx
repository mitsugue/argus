import React from 'react';

// v13.5.3 — NIKKEI MAIL INTAKE diagnostics (§6). Owner-facing truth: the
// panel must distinguish "no Nikkei email has arrived" from "ARGUS has
// stopped checking Gmail". Counters/states only — never message contents.
// The DEVICE VIEWPORT block is the real-device layout probe requested by the
// owner (persistent bottom band investigation): measured values only.

interface IntakeHealth {
  schemaVersion: string;
  status: string;
  configured: boolean;
  lastSyncAt: string | null;
  lastMessageAt: string | null;
  lastProcessedAt: string | null;
  lastEventAt: string | null;
  pending: number;
  parseFailures: number;
  quarantined: number;
  duplicatesSuppressed: number;
  aiAnalyses: number;
  aiCacheHits: number;
  emailsSeen: number;
  alertsEligible: number;
  lastCycleLatencySec: number | null;
  lastErrorClass: string | null;
  fallbackMode: string | null;
  threadAlive: boolean;
  hasCursor: boolean;
  seenCount: number;
  eventCount: number;
  observedSenderDomains: Record<string, { count: number; spf: boolean; dkim: boolean }>;
  allowedSenderDomains: string[];
  perSource?: Record<string, {
    state: string; observedCount?: number; lastAuthenticatedAt?: string | null;
    lastProcessedAt?: string | null; parseFailures?: number;
    quarantined?: number; lastMaterialEventAt?: string | null;
  }>;
  recentMessages?: Array<{ messageId: string; status: string;
    source: string | null; at: string }>;
  sourceAcceptance?: {
    perSource: Record<string, {
      verdict: string; classifiedEvents: number;
      severities: Record<string, number>; pendingTranslation: number;
      quarantined: number; parseFailures: number; observedCount: number;
      latestReceivedAt: string | null; latestProcessedAt: string | null;
    }>;
    acceptedSources: number;
    overallVerdict: string;
    acceptanceSemanticsJa?: string;
  };
  translationWorker?: {
    lastRunAt: string | null; lastSuccessAt: string | null;
    lastError: string | null; consecutiveFailures: number;
    translatedTotal: number; queueDepth: number; lastDrainAt: string | null;
    lastPolicyDecision?: string | null;
  };
  aiEscalations?: number;
  aiModels?: Record<string, {
    requestedModel?: string | null; returnedModel?: string | null;
    at?: string;
  }>;
}

// v13.5.26: the worker's cost-policy decision, in owner vocabulary — never
// pretend AI ran when the policy skipped it.
const POLICY_DECISION_JA: Record<string, string> = {
  allowed: 'AI実行 許可',
  deterministic_mode: 'AI停止中（決定論モード設定）',
  scheduled_daily_budget_exhausted: '本日のAI予算を使い切りました（明日再開）',
  scheduled_scope_required: 'この用途はAI対象外',
};

const ACCEPTANCE_JA: Record<string, string> = {
  REAL_MAIL_ACCEPTED: '実メール受理済み',
  NO_MAIL_RECEIVED_YET: '購読済・受信待ち',
  QUARANTINED: '検疫あり(要確認)',
  PARSER_FAILED: '解析失敗あり',
  AUTHENTICATION_FAILED: '認証失敗',
};

const SOURCE_LABEL_JA: Record<string, string> = {
  NIKKEI: '日経', FEDERAL_RESERVE_BOARD: 'FRB', US_TREASURY: '米財務省',
  BANK_OF_JAPAN: '日銀', BLS: '米労働統計局', EIA: '米EIA',
};

function baseUrl() {
  return (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)
    ?.replace(/\/$/, '') ?? null;
}

const STATUS_JA: Record<string, string> = {
  HEALTHY: '正常', DEGRADED: '一時劣化', MAILBOX_UNCONFIGURED: '未設定',
  OAUTH_EXPIRED: '認可期限切れ', RECONCILIATION_FAILED: '再照合失敗',
};

function rawSafeAreaInsets() {
  // Uncapped env() readout — the JS clamp in App.tsx rewrites the CSS var, so
  // diagnosing an oversized/duplicated inset needs a direct measurement.
  const probe = document.createElement('div');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText = [
    'position:fixed', 'visibility:hidden', 'pointer-events:none',
    'padding-top:env(safe-area-inset-top,0px)',
    'padding-bottom:env(safe-area-inset-bottom,0px)',
  ].join(';');
  document.documentElement.appendChild(probe);
  const style = window.getComputedStyle(probe);
  const top = Number.parseFloat(style.paddingTop);
  const bottom = Number.parseFloat(style.paddingBottom);
  probe.remove();
  return {
    top: Number.isFinite(top) ? Math.round(top) : null,
    bottom: Number.isFinite(bottom) ? Math.round(bottom) : null,
  };
}

function detectDisplayMode(): string {
  const modes = ['fullscreen', 'standalone', 'minimal-ui', 'browser'] as const;
  for (const mode of modes) {
    if (window.matchMedia?.(`(display-mode: ${mode})`).matches) return mode;
  }
  return 'unknown';
}

function viewportProbe() {
  const nav = document.querySelector('.nav');
  const rect = nav?.getBoundingClientRect();
  const style = getComputedStyle(document.documentElement);
  const env = rawSafeAreaInsets();
  return {
    innerH: window.innerHeight,
    visualH: Math.round(window.visualViewport?.height ?? 0),
    screenH: window.screen.height,
    safeBottom: style.getPropertyValue('--argus-safe-bottom').trim() || '—',
    envTopRaw: env.top != null ? `${env.top}px` : '—',
    envBottomRaw: env.bottom != null ? `${env.bottom}px` : '—',
    navBottom: rect ? Math.round(rect.bottom) : null,
    navGap: rect ? Math.round(window.innerHeight - rect.bottom) : null,
    standalone: (navigator as { standalone?: boolean }).standalone === true,
    displayMode: detectDisplayMode(),
  };
}

export const NewsIntakePanel: React.FC = () => {
  const [health, setHealth] = React.useState<IntakeHealth | null>(null);
  const [error, setError] = React.useState(false);
  const [probe, setProbe] = React.useState(() => viewportProbe());
  React.useEffect(() => {
    let cancelled = false;
    const base = baseUrl();
    if (!base) { setError(true); return undefined; }
    void (async () => {
      try {
        const response = await fetch(`${base}/api/argus/news-intake/health`,
          { cache: 'no-store', headers: { Accept: 'application/json' } });
        if (!response.ok) throw new Error(String(response.status));
        const body = await response.json() as IntakeHealth;
        if (!cancelled) setHealth(body);
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    const timer = window.setTimeout(() => setProbe(viewportProbe()), 800);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, []);

  const fmt = (iso: string | null | undefined) => (iso
    ? new Date(iso).toLocaleString('ja-JP', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    : '—');
  const rows: Array<[string, React.ReactNode]> = health ? [
    ['状態', `${STATUS_JA[health.status] ?? health.status} (${health.status})`],
    ['最終同期', fmt(health.lastSyncAt)],
    ['最終メール受信', fmt(health.lastMessageAt)],
    ['最終処理', fmt(health.lastProcessedAt)],
    ['最終イベント生成', fmt(health.lastEventAt)],
    ['受信メール数', health.emailsSeen],
    ['重複抑制', health.duplicatesSuppressed],
    ['検疫(送信元不一致)', health.quarantined],
    ['解析失敗', health.parseFailures],
    ['処理レイテンシ', health.lastCycleLatencySec != null
      ? `${health.lastCycleLatencySec}s` : '—'],
    ['取込モード', health.fallbackMode ?? '—'],
    ['カーソル保持', health.hasCursor ? 'あり' : 'なし'],
    ['イベント保持', health.eventCount],
  ] : [];

  return (
    <section id="settings-news-intake" className="card"
      aria-label="Nikkei mail intake diagnostics">
      <div className="section-head">
        <span className="section-head__title">NIKKEI MAIL INTAKE</span>
      </div>
      {!health && !error && <p className="cmd-alloc__note">確認中…</p>}
      {error && <p className="cmd-alloc__note">取込ヘルスを取得できません。</p>}
      {health && !health.configured && <p className="cmd-alloc__note">
        専用ニュースメールボックスは未設定です（MAILBOX_UNCONFIGURED）。
        設定手順はオーナーチェックリストを参照してください。</p>}
      {health && <div style={{ display: 'grid', gap: 4, fontSize: 11 }}
        data-argus-contract="news-intake-health-v1"
        data-intake-status={health.status}>
        {rows.map(([label, value]) => <div key={label}
          style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ color: 'var(--text-muted)' }}>{label}</span>
          <b>{value}</b>
        </div>)}
        {health.perSource && <div style={{ marginTop: 6 }}
          data-argus-contract="news-per-source-health-v1">
          <span style={{ color: 'var(--text-muted)' }}>ソース別</span>
          {Object.entries(health.perSource).map(([family, row]) => <div
            key={family} style={{ display: 'flex',
              justifyContent: 'space-between', gap: 8 }}>
            <span>{SOURCE_LABEL_JA[family] ?? family}</span>
            <b>{row.state === 'OBSERVED'
              ? `${row.observedCount}通 · 最終 ${fmt(row.lastAuthenticatedAt)}`
              + `${row.lastMaterialEventAt ? ' · 重要イベントあり' : ''}`
              : '購読済・受信待ち'}</b>
          </div>)}
        </div>}
        {health.sourceAcceptance && <div style={{ marginTop: 6 }}
          data-argus-contract="news-source-acceptance-v1"
          data-acceptance-verdict={health.sourceAcceptance.overallVerdict}>
          <span style={{ color: 'var(--text-muted)' }}>
            ソース別 受理実証（再起動をまたいで保持） · {
              health.sourceAcceptance.acceptedSources}/6ソース実証済み</span>
          {Object.entries(health.sourceAcceptance.perSource).map(([family, row]) => <div
            key={family} style={{ display: 'flex',
              justifyContent: 'space-between', gap: 8 }}>
            <span>{SOURCE_LABEL_JA[family] ?? family}</span>
            <b>{ACCEPTANCE_JA[row.verdict] ?? row.verdict}
              {row.classifiedEvents > 0 && ` · ${row.classifiedEvents}件`}
              {row.pendingTranslation > 0 && ` · 要約待ち${row.pendingTranslation}`}
              {row.quarantined > 0 && ` · 検疫${row.quarantined}`}
              {row.latestReceivedAt ? ` · 最終 ${fmt(row.latestReceivedAt)}` : ''}</b>
          </div>)}
          {health.sourceAcceptance.acceptanceSemanticsJa && <div
            style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 2 }}>
            {health.sourceAcceptance.acceptanceSemanticsJa}</div>}
        </div>}
        {health.translationWorker && <div style={{ marginTop: 6 }}>
          <span style={{ color: 'var(--text-muted)' }}>日本語要約ワーカー（常時稼働）</span>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span>待ち{health.translationWorker.queueDepth}件 · 累計{
              health.translationWorker.translatedTotal}件</span>
            <b>{health.translationWorker.lastError
              ? `エラー: ${health.translationWorker.lastError}`
              : `最終成功 ${fmt(health.translationWorker.lastSuccessAt)}`}</b>
          </div>
          {health.translationWorker.lastPolicyDecision && <div
            style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span style={{ color: 'var(--text-muted)' }}>直近のAI実行判定</span>
            <b>{POLICY_DECISION_JA[health.translationWorker.lastPolicyDecision]
              ?? health.translationWorker.lastPolicyDecision}</b>
          </div>}
        </div>}
        {health.aiModels && Object.keys(health.aiModels).length > 0
          && <div style={{ marginTop: 6 }}>
          <span style={{ color: 'var(--text-muted)' }}>
            AI意味解析モデル（実測） {(health.aiEscalations ?? 0) > 0
              && `· 上位エスカレーション${health.aiEscalations}件`}</span>
          {Object.entries(health.aiModels).map(([lane, row]) => <div key={lane}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
            <span>{lane === 'sol' ? '上位（重大・困難のみ）' : '標準'}</span>
            <b style={{ fontFamily: 'monospace' }}>
              {row.returnedModel ?? row.requestedModel ?? '—'}</b>
          </div>)}
        </div>}
        {(health.recentMessages ?? []).length > 0 && <div style={{ marginTop: 6 }}>
          <span style={{ color: 'var(--text-muted)' }}>直近メール処理状態</span>
          {(health.recentMessages ?? []).slice(0, 8).map((row) => <div
            key={row.messageId} style={{ display: 'flex',
              justifyContent: 'space-between', gap: 8 }}>
            <span style={{ fontFamily: 'monospace' }}>{row.messageId.slice(0, 10)}…
              {row.source ? ` ${SOURCE_LABEL_JA[row.source] ?? row.source}` : ''}</span>
            <b>{row.status}</b>
          </div>)}
        </div>}
        {Object.keys(health.observedSenderDomains ?? {}).length > 0
          && <div style={{ marginTop: 4 }}>
            <span style={{ color: 'var(--text-muted)' }}>観測済み送信元ドメイン</span>
            {Object.entries(health.observedSenderDomains).map(([domain, p]) =>
              <div key={domain} style={{ display: 'flex',
                justifyContent: 'space-between' }}>
                <span>{domain}</span>
                <b>{p.count}通 {p.spf ? 'SPF✓' : ''} {p.dkim ? 'DKIM✓' : ''}</b>
              </div>)}
          </div>}
      </div>}

      <div className="section-head" style={{ marginTop: 12 }}>
        <span className="section-head__title">DEVICE VIEWPORT（表示診断）</span>
      </div>
      <div style={{ display: 'grid', gap: 3, fontSize: 11 }}
        data-argus-contract="viewport-probe-v1">
        {([
          ['window.innerHeight', probe.innerH],
          ['visualViewport.height', probe.visualH],
          ['screen.height', probe.screenH],
          ['safe-area-bottom', probe.safeBottom],
          ['env(top) 生値', probe.envTopRaw],
          ['env(bottom) 生値', probe.envBottomRaw],
          ['ナビ下端の実測位置', probe.navBottom ?? '—'],
          ['ナビ下端〜ビューポート末尾', probe.navGap != null
            ? `${probe.navGap}px` : '—'],
          ['standalone(PWA)', probe.standalone ? 'yes' : 'no'],
          ['display-mode', probe.displayMode],
        ] as const).map(([label, value]) => <div key={label}
          style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <span style={{ color: 'var(--text-muted)' }}>{label}</span>
          <b>{String(value)}</b>
        </div>)}
      </div>
      <p className="cmd-alloc__note">
        本文は保存されません。取込は読み取り専用の専用メールボックスに限定されます。
      </p>
    </section>
  );
};

export default NewsIntakePanel;
