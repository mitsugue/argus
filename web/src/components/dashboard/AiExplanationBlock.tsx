import React from 'react';
import { aiExplanationDisplay } from '../../lib/aiExplanationState';
import { investigateNow, type InvestigateNowResult } from '../../lib/queueRequests';

// ARGUS V11.5.4 — 「理由を詳しく調べる」 is no longer a mere queue ticket. Clicking runs
// an IMMEDIATE bounded source sweep on the server (official → professional metadata →
// discovery → public article probe → alternative chasing; no LLM, no paywall bypass)
// and shows what was searched, what was found fresh, and what was blocked.
// The AI explanation stays a separate queued path and is only a secondary note —
// 「次回自動生成で反映」 must never be the primary result of the button.

interface Props {
  explanationJa?: string | null;
  explanationStatus?: string | null;
  symbol?: string;
  market?: string;
  context: 'cause-stack' | 'mover-card' | 'downside-card' | string;
  /** compact styling for dense cards (downside/mover) */
  dense?: boolean;
  /** v12.0.8: ボタン文言の上書き(例: 「この原因を再確認」)。 */
  labelJa?: string;
}

function hhmm(iso?: string): string {
  return iso ? String(iso).slice(11, 16) : '';
}

const SOURCE_LABEL: Record<string, string> = {
  tdnet: 'TDnet', official_events_store: '公式イベント', sec_edgar: 'SEC EDGAR',
  google_news_jp: 'Google News JP', google_news_us: 'Google News US',
  finnhub_company_news: 'Finnhub',
};

function sourceJa(s: string): string {
  if (SOURCE_LABEL[s]) return SOURCE_LABEL[s];
  if (s.startsWith('caos_feeds')) return '日経/ロイター/NHK/Bloomberg/CNBC等フィード';
  if (s.startsWith('article_probe:')) return `公開本文(${s.split(':')[1] || 'web'})`;
  return s;
}

export function AiExplanationBlock({ explanationJa, explanationStatus, symbol, market, context, dense, labelJa }: Props) {
  const [investigating, setInvestigating] = React.useState(false);
  const [result, setResult] = React.useState<InvestigateNowResult | null>(null);
  const disp = aiExplanationDisplay(explanationJa, explanationStatus);
  const faint: React.CSSProperties = { color: 'var(--text-faint)', fontSize: dense ? 11 : 12, margin: 0 };

  // cached explanation renders ABOVE the button — the 念押し sweep stays available
  const cachedBlock = disp.mode === 'expandable' ? (
    dense ? (
      <p className="dic-line" style={{ margin: 0 }}><b>AI解説:</b> {explanationJa}</p>
    ) : (
      <details className="ai-expl" style={{ marginTop: 6 }}>
        <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--accent)' }}>{disp.labelJa}</summary>
        <p style={{ margin: '6px 0 0', fontSize: 12, lineHeight: 1.7 }}>{explanationJa}</p>
      </details>
    )
  ) : null;

  const onClick = async () => {
    if (investigating || !symbol) return;
    setInvestigating(true);
    setResult(null);
    const res = await investigateNow(symbol, String(market || 'JP'), context);
    setResult(res ?? { ok: false, status: 'error', symbol: symbol || '', market: String(market || 'JP'),
                       messageJa: '調査リクエストに失敗しました。時間をおいて再度お試しください。' });
    setInvestigating(false);
  };

  return (
    <div style={{ marginTop: 6 }}>
      {cachedBlock}
      {/* the always-available 念押し button (never a dead button) */}
      <button
        type="button"
        onClick={onClick}
        disabled={investigating}
        style={{
          fontSize: dense ? 11 : 12, cursor: investigating ? 'default' : 'pointer',
          background: 'transparent', color: 'var(--accent)',
          border: '1px solid var(--line)', borderRadius: 6, padding: '3px 10px',
        }}
      >{investigating ? '最新材料を調査中…' : (labelJa ?? '理由を詳しく調べる')}</button>

      {!result && !investigating && (
        <span style={{ ...faint, display: 'block', marginTop: 4 }}>
          押すと、その場で公式開示・直近ニュース・公開メタデータ・検索結果を再確認します(公開画面からAIは起動しません)。
          {disp.mode === 'chip' ? ` ${disp.labelJa}。` : ''}
        </span>
      )}

      {result && result.status === 'rate_limited' && (
        <p style={{ ...faint, marginTop: 6 }}>
          {result.messageJa || '直前に確認済みです。'}
          {result.nextCheckAt ? ` 次回確認: ${hhmm(result.nextCheckAt)}UTC` : ''}
        </p>
      )}

      {result && result.status !== 'rate_limited' && (
        <div style={{ marginTop: 6, fontSize: dense ? 11 : 12 }}>
          <p style={{ margin: 0, fontWeight: 600 }}>
            {result.status === 'partial' ? '一部ソースのみ確認できました' : '最新材料を確認しました'}
            {(result.sweep?.freshItems?.length ?? 0) > 0
              ? ` — 新しい材料 ${result.sweep!.freshItems.length}件を反映`
              : ' — 新しい材料は見つかりませんでした'}
          </p>
          {result.bestCurrentLeadJa && (
            <p style={{ margin: '3px 0 0' }}><b>現在の最有力:</b> {result.bestCurrentLeadJa}</p>
          )}
          {(result.sweep?.freshItems ?? [])
            .slice()
            .sort((a, b) => (a.ageHours ?? Infinity) - (b.ageHours ?? Infinity))
            .slice(0, 3).map((it, i) => (
            <p key={i} style={{ margin: '2px 0 0', color: 'var(--text-sub)' }}>
              ・{it.displayTitleJa || it.title}
              <span style={{ color: 'var(--text-faint)', fontSize: 10, marginLeft: 6 }}>
                {it.truePublisher}{it.ageHours != null ? ` · ${it.ageHours < 1 ? '1h以内' : `${Math.floor(it.ageHours)}h前`}` : ''}
              </span>
            </p>
          ))}
          {(result.sweep?.notFoundJa ?? []).map((x, i) => (
            <p key={`nf${i}`} style={{ ...faint, margin: '2px 0 0' }}>・{x}</p>
          ))}
          <p style={{ ...faint, margin: '4px 0 0' }}>
            確認済み: {(result.sweep?.searchedSources ?? []).map(sourceJa).join(' / ') || '—'}
          </p>
          {(result.sweep?.blockedSources?.length ?? 0) > 0 && (
            <p style={{ ...faint, margin: '2px 0 0' }}>
              取得できなかったソース: {result.sweep!.blockedSources.map((b) => `${b.source}(${b.reason})`).join(' / ')}
              {result.sweep!.alternativeSourcesChecked.length > 0 &&
                ` → 代替確認: ${result.sweep!.alternativeSourcesChecked.slice(0, 3).join(' / ')}`}
            </p>
          )}
          {/* AI explanation is a SECONDARY note, never the primary result */}
          <p style={{ ...faint, margin: '4px 0 0' }}>
            {explanationJa && explanationJa.trim()
              ? 'AI解説を開けます(上の「AI解説を開く」)。'
              : (result.aiExplanation?.messageJa || 'AI解説は別途生成待ちです(補足)。')}
          </p>
        </div>
      )}
    </div>
  );
}

export default AiExplanationBlock;
