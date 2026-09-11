import React, { useState } from 'react';
import { newsAnalysisStatusJa, displayNewsHeadline } from '../../lib/newsHeadline';
import { useNewsIntelligence, type NewsIntelEvent, type NewsIntelView } from '../../hooks/useNewsIntelligence';
import { useMarketShock } from '../../hooks/useMarketShock';
import './NewsAlertsPanel.css';

// v13.5.60 (owner iPhone review 2026-09-07): the Alerts page opens with the
// ニュース・市場リスク section — every material news-intelligence event
// (HIGH/CRITICAL, not stale) and every corroborated market shock, with the
// full interpretation that Today only summarises. Evidence only: nothing here
// carries action authority, and the SDA is untouched.

export const NEWS_ALERTS_SECTION_ID = 'news-intel';

const SEVERITY_TONE: Record<string, string> = {
  CRITICAL: 'var(--value-negative)', HIGH: 'var(--amber, #fbbf24)',
  MEDIUM: 'var(--accent)', LOW: 'var(--text-muted)',
  WATCH: 'var(--text-muted)', INFO: 'var(--text-faint)',
};
const DIRECTION_JA: Record<string, string> = {
  BULLISH: '強気', BEARISH: '弱気', MIXED: '混在', UNCLEAR: '方向判定不能',
};

export function materialNewsEvents(events: NewsIntelEvent[]): NewsIntelEvent[] {
  return events
    .filter((event) => (event.severity === 'HIGH' || event.severity === 'CRITICAL')
      && String(event.staleness).toUpperCase() !== 'STALE')
    .filter((event, index, rows) => rows.findIndex((candidate) =>
      candidate.eventId === event.eventId) === index)
    .sort((left, right) => (right.severity === 'CRITICAL' ? 1 : 0)
      - (left.severity === 'CRITICAL' ? 1 : 0)
      || String(right.sourceReceivedAt ?? '').localeCompare(String(left.sourceReceivedAt ?? '')));
}

const receivedJa = (value: string | null | undefined): string => {
  if (!value) return '—';
  const t = Date.parse(value);
  if (!Number.isFinite(t)) return '—';
  return new Date(t).toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  });
};

export const NewsHistory: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<NewsIntelView | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const load = async () => {
    if (loading) return;
    setLoading(true); setError(false);
    try {
      const base = (import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined)?.replace(/\/$/, '');
      if (!base) throw new Error('backend_missing');
      const response = await fetch(`${base}/api/argus/news-intelligence?view=history`, { cache: 'no-store' });
      if (!response.ok) throw new Error('history_unavailable');
      const data = await response.json() as NewsIntelView;
      if (data.schemaVersion !== 'argus-news-intelligence-v1' || !Array.isArray(data.events)) {
        throw new Error('history_invalid');
      }
      setView(data);
    } catch { setError(true); } finally { setLoading(false); }
  };
  return <div className="news-alerts__group" data-news-history>
    <button type="button" aria-expanded={open} onClick={() => {
      setOpen(!open); if (!open && !view) void load();
    }}>過去の重要ニュースを見る</button>
    {open && <>
      <p className="news-alerts__note">受信から24時間を過ぎた直近7日間の保存記事です。保存は最近の記事を含め最大40件で、全記事の一覧ではありません。当時の説明であり、現在の速報・売買判断ではありません。</p>
      {loading && <p role="status">履歴を読み込み中…</p>}
      {error && <p role="status">履歴を更新できません。{view ? '前回取得した履歴を表示しています。' : '記事が無いという意味ではありません。'}</p>}
      {view && <small>最終取得 {receivedJa(view.generatedAt)} JST</small>}
      {!loading && <button type="button" onClick={() => void load()}>履歴を再取得</button>}
      {view?.events.length === 0 && <p>保存されている対象記事はありません。</p>}
      {view?.events.map(event => <article key={event.eventId} className="news-alerts__item"
        id={`news-history-${event.eventId}`} data-news-history-event={event.eventId}>
        <p className="news-alerts__title"><b>{displayNewsHeadline(event.headlineJa)}</b></p>
        <p className="news-alerts__why">当時の解釈: {event.whyJa}</p>
        {event.japanImpactJa && <p className="news-alerts__japan">当時の日本株への見立て: {event.japanImpactJa}</p>}
        <p className="news-alerts__meta">{event.source} · 受信 {receivedJa(event.sourceReceivedAt)} JST · 過去の情報 · {newsAnalysisStatusJa(event.analysisState, event.analysisInputScope)}</p>
      </article>)}
    </>}
  </div>;
};

export const NewsAlertsPanel: React.FC = () => {
  const news = useNewsIntelligence();
  const shock = useMarketShock();
  const material = materialNewsEvents(news.view?.events ?? []);
  const shocks = shock.view?.events ?? [];
  const unread = news.status === 'error' && news.view == null;
  return (
    <section id={NEWS_ALERTS_SECTION_ID} className="news-alerts card" aria-label="ニュース・市場リスク">
      <div className="news-alerts__head">
        <b>ニュース・市場リスク</b>
        <span>{material.length + shocks.length}件 · 売買権限なし</span>
      </div>
      {shocks.length > 0 && <div className="news-alerts__group">
        <small>市場リスク（市場横断で確認された衝撃）</small>
        {shocks.map((event) => <article key={event.eventId} className="news-alerts__item"
          id={`news-${event.eventId}`} data-severity={event.severity}>
          <p className="news-alerts__title">
            <mark style={{ color: SEVERITY_TONE[event.severity] ?? 'inherit',
              borderColor: SEVERITY_TONE[event.severity] ?? 'inherit' }}>{event.severity}</mark>
            <b>{displayNewsHeadline(event.headlineJa)}</b>
          </p>
          <p className="news-alerts__why">{event.whyJa}</p>
          <p className="news-alerts__meta">
            {event.sources.map((source) => source.name).join(' · ')}
            {event.asOf ? ` · ${event.asOf}` : ''}
            {event.crossMarket.confirmed && ` · 市場横断確認: ${event.crossMarket.signals.join('/')}`}
          </p>
        </article>)}
      </div>}
      <div className="news-alerts__group">
        <small>重大ニュース（ARGUSの解釈 · 記事本文ではありません）</small>
        {news.status === 'loading' && material.length === 0
          && <p className="news-alerts__empty">読み込み中…</p>}
        {news.status !== 'loading' && material.length === 0 && <p className="news-alerts__empty">
          {unread ? 'ニュースを取得できていません（重大ニュースが無いという意味ではありません）'
            : '直近の重大ニュースなし（INFO/WATCH級は表示しません）'}
        </p>}
        {material.map((event) => {
          const direction = event.impactDirection?.primaryDirection ?? 'UNCLEAR';
          return <article key={event.eventId} className="news-alerts__item"
            id={`news-${event.eventId}`} data-severity={event.severity}>
            <p className="news-alerts__title">
              <mark style={{ color: SEVERITY_TONE[event.severity] ?? 'inherit',
                borderColor: SEVERITY_TONE[event.severity] ?? 'inherit' }}>{event.severity}</mark>
              <em>{DIRECTION_JA[direction] ?? direction}</em>
              <b>{displayNewsHeadline(event.headlineJa)}</b>
            </p>
            <p className="news-alerts__why">{event.whyJa}</p>
            {event.japanImpactJa && event.japanImpactJa !== event.whyJa
              && <p className="news-alerts__japan">日本株への波及: {event.japanImpactJa}</p>}
            {event.marketReadings.length > 0 && <p className="news-alerts__readings">
              {event.marketReadings.slice(0, 4).map((reading) =>
                `${reading.labelJa} ${reading.value ?? '—'}${reading.unit}`).join(' · ')}
            </p>}
            <p className="news-alerts__meta">
              {event.source} · 受信 {receivedJa(event.sourceReceivedAt)} JST ·{' '}
              {event.confirmationState === 'MARKET_CONFIRMED' ? '市場確認済み' : '市場確認待ち'}
              {' · '}{newsAnalysisStatusJa(event.analysisState, event.analysisInputScope)}
              {event.backfill ? ' · 再処理(過去分)' : ''}
            </p>
          </article>;
        })}
      </div>
      <NewsHistory />
      <p className="news-alerts__note">
        方向判定不能 = このニュースからは上下を決めない、という判定です。ニュースは売買権限を持ちません。
      </p>
    </section>
  );
};

export default NewsAlertsPanel;
