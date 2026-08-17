import '../dashboard/Dashboard.css';
import React from 'react';
import { usePaidSources, type PaidProvider } from '../../hooks/usePaidSources';

// 有料データ接続状況 (v11.1) — honest per-provider status. '設定済み' ≠ 'ライブ取得成功'.
// Only providers that returned real data (live) are green; configured-but-unverified is
// amber; missing is grey.

const LABEL: Record<string, string> = {
  'jquants-core': 'J-Quants Standard（コア）',
  'jquants-tdnet': 'TDnet Document Add-on（公式開示）',
  'edinet': 'EDINET（公式開示）',
  'twelvedata-quote': 'Twelve Data Grow（quote）',
  'twelvedata-timeseries': 'Twelve Data Grow（time_series）',
  'fred': 'FRED（金利/VIX）',
  'finnhub': 'Finnhub（ニュース/相場）',
  'alphavantage': 'AlphaVantage（米ムーバー）',
  'coingecko': 'CoinGecko（暗号資産）',
  'openai': 'OpenAI（AI判断）',
  'gemini': 'Gemini（AIチェック）',
  'layer2b-private-store': 'Layer2B private store',
};
const STATUS: Record<string, { ja: string; tone: string }> = {
  live: { ja: 'ライブ取得成功', tone: 'var(--value-positive,#34d399)' },
  partial: { ja: '一部のみ', tone: 'var(--amber,#fbbf24)' },
  configured: { ja: '設定済み（未疎通）', tone: 'var(--amber,#fbbf24)' },
  not_live: { ja: '設定済みだが未成功', tone: 'var(--amber,#fbbf24)' },
  missing: { ja: '未設定', tone: 'var(--text-muted)' },
};

const Row: React.FC<{ p: PaidProvider }> = ({ p }) => {
  const s = STATUS[p.status] ?? STATUS.not_live;
  return (
    <div className="mdepth__row">
      <span className="mdepth__label">{LABEL[p.provider] ?? p.provider}</span>
      <span className="mdepth__status" style={{ color: s.tone }}>{s.ja}</span>
    </div>
  );
};

export const PaidSourceStatusCard: React.FC = () => {
  const d = usePaidSources();
  if (!d || !d.providers) return null;
  return (
    <section className="mdepth">
      <div className="section-head">
        <span className="section-head__title">有料データ接続状況</span>
        <span className="section-head__count">{d.summary?.live ?? 0}/{d.summary?.total ?? d.providers.length} live</span>
      </div>
      <div className="card mdepth__card">
        <p className="mdepth__lead">
          <b>「設定済み」と「ライブ取得成功」は別です。</b>ARGUS Proでは、キーがあるだけではliveとは表示しません。
          実際のprovider response・timestamp・sample countを確認できたものだけliveと表示します。
        </p>
        <div className="mdepth__grid">
          {d.providers.map((p) => <Row key={p.provider} p={p} />)}
        </div>
        <p className="mdepth__note">
          TDnetは公式(J-Quants Add-on)を優先し、失敗時のみ非公式(yanoshin)フォールバック。公式開示は
          official confirmation＝事実の確認で、materialな題目のみofficial_catalyst候補。価格原因の確定には
          market/timingの確認が必要です。Twelve Data Growはquota拡張であり、板(L2)/歩み値/オプション/貸株料の
          代替ではありません。
        </p>
      </div>
    </section>
  );
};
