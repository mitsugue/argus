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
}

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
