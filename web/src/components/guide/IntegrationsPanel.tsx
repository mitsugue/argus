import React from 'react';
import { useIntegrations } from '../../hooks/useIntegrations';
import type { IntegrationProvider, RuntimeStatus } from '../../types/integrations';
import './IntegrationsPanel.css';

// Status → color + short English label. Honest about missing/disabled/pending.
const STATUS_META: Record<RuntimeStatus, { color: string; label: string }> = {
  live:                   { color: 'var(--green)',     label: 'live' },
  partial:                { color: 'var(--amber)',     label: 'partial' },
  mock:                   { color: 'var(--amber)',     label: 'mock' },
  no_cached_result:       { color: 'var(--blue)',      label: 'not run yet' },
  pending:                { color: 'var(--blue)',      label: 'pending' },
  pending_local_validation: { color: 'var(--blue)',    label: 'pending (local validation)' },
  disabled:               { color: 'var(--text-muted)', label: 'disabled' },
  missing:                { color: 'var(--red)',       label: 'missing' },
  unknown:                { color: 'var(--text-muted)', label: 'unknown' },
};

function StatusPill({ status }: { status: RuntimeStatus }) {
  const m = STATUS_META[status] ?? { color: 'var(--text-muted)', label: status };
  return (
    <span className="intg__pill" style={{ color: m.color, borderColor: m.color }}>
      {m.label}
    </span>
  );
}

function ProviderRow({ p }: { p: IntegrationProvider }) {
  return (
    <div className="intg__row">
      <span className="intg__label">{p.label}</span>
      <StatusPill status={p.runtimeStatus} />
      <span className="intg__used">{p.usedFor.join(' · ')}</span>
      <span className="intg__note">{p.notesJa}</span>
    </div>
  );
}

// JP clarifications — the truthful AI-billing story.
const AI_NOTES_JA = [
  'GPT-5.5 Pro Handoff は手動コピー&ペーストで、API課金は一切ありません（ChatGPT の画面に貼って使います）。',
  'OpenAI API は ChatGPT Pro サブスクとは別請求です。自動AI判断には OpenAI / Gemini の API キーが必要です。',
  '自動AI判断は Render の環境変数（OPENAI_API_KEY / GEMINI_API_KEY / AI_JUDGE_ENABLED）と管理者による実行が揃って初めて live になります。',
  '公開フロントエンドが高コストなAI呼び出しを自動で行うことはありません（キャッシュの読み取りのみ）。',
];

export const IntegrationsPanel: React.FC = () => {
  const { data, phase } = useIntegrations();
  if (!data) {
    return (
      <div className="card guide-card">
        <p className="guide-note">接続状況を取得中…</p>
      </div>
    );
  }

  const market = data.providers.filter((p) => p.category === 'market_data' || p.category === 'news_catalyst');
  const ai = data.providers.filter((p) => p.category === 'ai');
  const flow = data.providers.filter((p) => p.category === 'flow_orderbook');
  const overallColor = phase === 'live' ? 'var(--green)' : phase === 'partial' ? 'var(--amber)' : 'var(--text-muted)';

  return (
    <div className="card guide-card intg">
      <div className="intg__head">
        <span className="intg__overall" style={{ color: overallColor, borderColor: overallColor }}>
          {phase}
        </span>
        <span className="intg__head-note">プロバイダ設定・稼働状況（シークレットは表示しません）</span>
      </div>

      <div className="intg__group">
        <div className="intg__group-title">Market Data</div>
        {market.map((p) => <ProviderRow key={p.id} p={p} />)}
      </div>

      <div className="intg__group">
        <div className="intg__group-title">AI</div>
        {ai.map((p) => <ProviderRow key={p.id} p={p} />)}
        {/* GPT-5.5 Pro Handoff is manual + free — not a billed API path. */}
        <div className="intg__row">
          <span className="intg__label">GPT-5.5 Pro Handoff</span>
          <span className="intg__pill" style={{ color: 'var(--green)', borderColor: 'var(--green)' }}>live (manual)</span>
          <span className="intg__used">pro-handoff</span>
          <span className="intg__note">手動コピー&ペースト。API呼び出しなし・無料。</span>
        </div>
        <div className="intg__ai-summary">
          自動AI判断ステータス: <b>{data.aiJudgment.truthStatus}</b>
          {' '}(OpenAI key: {data.aiJudgment.openaiConfigured ? '✓' : '✗'},
          {' '}Gemini key: {data.aiJudgment.geminiConfigured ? '✓' : '✗'},
          {' '}AI_JUDGE_ENABLED: {data.aiJudgment.enabled ? 'true' : 'false'},
          {' '}cached: {data.aiJudgment.hasCachedResult ? 'yes' : 'no'})
        </div>
      </div>

      {flow.length > 0 && (
        <div className="intg__group">
          <div className="intg__group-title">Flow / Order book</div>
          {flow.map((p) => <ProviderRow key={p.id} p={p} />)}
        </div>
      )}

      <ul className="intg__notes">
        {AI_NOTES_JA.map((n, i) => <li key={i}>{n}</li>)}
      </ul>

      <div className="intg__roadmap">
        <span className="intg__group-title">Next API roadmap</span>
        <ol>
          {data.nextRecommendedApis.map((n) => <li key={n}>{n}</li>)}
        </ol>
      </div>
    </div>
  );
};
