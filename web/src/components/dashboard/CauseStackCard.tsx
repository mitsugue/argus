import React from 'react';
import { useCauseAttribution } from '../../hooks/useCauseAttribution';
import { freshnessLineJa, marketConfLineJa } from './DownsideIncidentCard';
import { aiExplanationDisplay, newsDisplayTitleJa } from '../../lib/aiExplanationState';
import { AiExplanationBlock } from './AiExplanationBlock';
import { autoQueueTranslations } from '../../lib/queueRequests';
import './CauseStackCard.css';

// Cause-stack card (v10.117) — the integrity view for a material move: what is
// the confirmed immediate trigger (often NONE), the likely-cause distribution
// (with a non-zero UNKNOWN), how far it propagated, positioning context (no named
// institution), and what would change the conclusion. Decision-support only.

const CAUSE_JA: Record<string, string> = {
  EARNINGS_RESULT_SHOCK: '決算結果ショック', PRE_EARNINGS_DE_RISKING: '決算前の手仕舞い',
  CROWDED_TRADE_UNWIND: '人気トレードの巻き戻し', VALUATION_REPRICING: 'バリュエーション調整',
  RATE_SHOCK: '金利ショック', AI_CAPEX_ROI_CONCERN: 'AI設備投資ROI懸念',
  SECTOR_WIDE_DELEVERAGING: 'セクター全体の手仕舞い', LONG_LIQUIDATION: 'ロング解消',
  NEW_SHORT_BUILDUP: '新規空売り', SHORT_COVERING: '買い戻し', DISTRIBUTION: '大口の売り',
  COMPANY_SPECIFIC_CATALYST: '個別材料', UNKNOWN: '原因未確認',
};
const SCOPE_JA: Record<string, string> = {
  company_specific: '個別銘柄', subsector_wide: 'サブセクター', sector_wide: 'セクター全体',
  cross_market: 'クロスマーケット', global_growth_unwind: 'グローバル景気の巻き戻し', unconfirmed: '未確認',
};
const POS_JA: Record<string, string> = {
  newLongAccumulation: '新規ロング', longLiquidation: 'ロング解消', newShortBuildup: '新規空売り',
  shortCovering: '買い戻し', distribution: '大口売り', retailNoise: '個人ノイズ', unknown: '不明',
};
const NEWS_CLS_JA: Record<string, string> = {
  CONFIRMED: '確定(公式・時刻整合)', LIKELY_RELATED: '関連の可能性', BACKGROUND: '背景', UNCONFIRMED: '因果不明',
};
// v11.3.3 Mover Cause ladder — 原因確定と候補を分離して表示する。
const LADDER_TONE: Record<string, string> = {
  confirmed_cause: 'var(--value-negative, #f87171)',
  probable_catalyst: 'var(--amber, #fbbf24)',
  candidate_catalyst: 'var(--text-main)',
  no_lead_yet: 'var(--text-faint)',
  not_scoreable: 'var(--text-faint)',
};
const TIMING_JA: Record<string, string> = {
  before_move: '値動き前', during_move: '値動き中', after_move: '値動き後', unknown: '時刻未確認',
};
const CORRO_JA: Record<string, string> = {
  official: '公式', multi_source: '複数ソース', market_confirmed: '市場確認',
  single_source: '単一ソース', none: '未裏取り',
};

export const CauseStackCard: React.FC<{ symbol: string; market?: string }> = ({ symbol, market = 'JP' }) => {
  const { data } = useCauseAttribution(symbol, market);
  // v11.5.1: AI explanation is cached-only. Fetch the cached explanation (explain=1
  // is cache-read on the backend — no LLM) once per symbol, then render a STATE, never
  // a dead "表示" button.
  const [expl, setExpl] = React.useState<{
    text?: string | null; status?: string; generatedAt?: string | null;
    unverified?: string[]; whatConfirm?: string; whatRefute?: string;
  } | null>(null);
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL as string | undefined;
    if (!backend || !symbol) return;
    let alive = true;
    fetch(`${backend.replace(/\/$/, '')}/api/argus/cause-attribution?symbol=${encodeURIComponent(symbol)}&market=${market}&explain=1`)
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        setExpl({
          text: d.explanationJa,
          status: d.explanationStatus || d.moverCause?.explanationStatus,
          generatedAt: d.explanationGeneratedAt,
          unverified: d.unverifiedAssumptions, whatConfirm: d.whatWouldConfirmJa, whatRefute: d.whatWouldRefuteJa,
        });
      })
      .catch(() => { /* keep null → not_generated state */ });
    return () => { alive = false; };
  }, [symbol, market]);
  const ai = aiExplanationDisplay(expl?.text, expl?.status);

  // v11.5.2: guarantee visible English news enters the translation queue. Once per
  // (symbol, session): POST the pending titles, then flip the chip to 翻訳リクエスト済み.
  const [newsRequested, setNewsRequested] = React.useState(false);
  React.useEffect(() => {
    const pend = (data?.news || [])
      .filter((n) => (n.translationStatus === 'pending' || n.translationStatus === 'failed') && n.titleOriginal)
      .map((n) => ({ titleOriginal: String(n.titleOriginal), source: n.source, publishedAt: n.time ?? undefined }));
    if (!pend.length) return;
    autoQueueTranslations(`cause-stack|${market}:${symbol}`, 'cause-stack', symbol, market, pend);
    setNewsRequested(true);
  }, [data, symbol, market]);

  // v10.190: no longer early-returns on missing data. The "なぜ動いた?" button is
  // ALWAYS available on every expanded stock (owner asked: 全銘柄で押せるように),
  // and the detailed cause stack renders only when attribution data is present.
  const causes = data ? Object.entries(data.causeProbabilities || {}).sort((a, b) => b[1] - a[1]).slice(0, 4) : [];
  const posTop = data ? Object.entries(data.positioning?.probabilities || {}).sort((a, b) => b[1] - a[1])[0] : undefined;
  const material = !!data && typeof data.changePct === 'number' && Math.abs(data.changePct) >= 2;

  return (
    <section className="csc-card">
      <header className="csc-head">
        <h2>{material ? '原因の詳細' : '値動きの背景'}</h2>
        {data && <span className="csc-sym">{data.symbol}{typeof data.changePct === 'number' ? ` ${data.changePct.toFixed(1)}%` : ''}</span>}
      </header>

      <div className="csc-why">
        {ai.mode === 'expandable' ? (
          <details className="csc-ai">
            <summary style={{ cursor: 'pointer', fontWeight: 600, color: 'var(--text-main)' }}>
              🔎 {ai.labelJa}{expl?.generatedAt ? ` ・生成 ${String(expl.generatedAt).slice(11, 16)}` : ''}
            </summary>
            <p className="csc-why-text">{expl?.text}</p>
            {(expl?.unverified || []).length > 0 && (
              <p className="csc-why-note">未検証の仮定: {(expl?.unverified || []).join(' / ')}</p>
            )}
            {expl?.whatConfirm && <p className="csc-why-note">確定条件: {expl.whatConfirm}</p>}
            {expl?.whatRefute && <p className="csc-why-note">否定条件: {expl.whatRefute}</p>}
            <p className="csc-why-note">要確認・投資助言ではありません。</p>
          </details>
        ) : (
          // v11.5.2: not_generated → clickable「理由を詳しく調べる」(enqueues only);
          // queued/pending/… → non-clickable chip. Never a dead button.
          <AiExplanationBlock
            explanationJa={expl?.text}
            explanationStatus={expl?.status}
            symbol={data?.symbol || symbol}
            market={market}
            context="cause-stack"
          />
        )}
      </div>

      {data && (<>
      {/* v11.3.3 Mover Cause ladder — replaces the bare 確認できず/原因未確認 row */}
      {data.moverCause?.causeStatusJa ? (
        <div className="csc-trigger" style={{ display: 'block' }}>
          <div>
            <span className="csc-k">原因判定</span>
            <b style={{ color: LADDER_TONE[data.moverCause.causeStatus ?? ''] || 'var(--text-main)' }}>
              {data.moverCause.causeStatusJa}
            </b>
            {data.moverCause.bestLeadJa && <span className="csc-v"> — {data.moverCause.bestLeadJa}</span>}
          </div>
          {(data.moverCause.topCandidates ?? [])
            .filter((c) => !c.titleJa || !(data.moverCause?.bestLeadJa || '').includes(c.titleJa))
            .slice(0, 2).map((c, i) => {
            const past = c.newsFreshness?.freshness === 'old' || c.newsFreshness?.freshness === 'stale';
            return (
            <p key={i} style={{ margin: '2px 0 0', fontSize: 12,
                                color: past ? 'var(--text-faint)' : 'var(--text-sub)' }}>
              ・{c.titleJa} <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>
                ({TIMING_JA[c.timingRelation ?? 'unknown']}・{CORRO_JA[c.corroborationLevel ?? 'none']})</span>
              {past && (
                <span style={{ fontSize: 10, color: 'var(--text-faint)', border: '1px solid var(--line)',
                               borderRadius: 999, padding: '0 6px', marginLeft: 6 }}>
                  {c.newsFreshness?.ageHours != null ? `過去材料(${Math.floor((c.newsFreshness.ageHours || 0) / 24)}日前)` : '過去材料'}
                </span>
              )}
              {c.translationStatus === 'pending' && c.titleOriginal && (
                <details style={{ display: 'inline' }}>
                  <summary style={{ display: 'inline', cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)', marginLeft: 6 }}>原文を見る</summary>
                  <span style={{ color: 'var(--text-faint)', fontSize: 11 }}> {c.titleOriginal}</span>
                </details>
              )}
            </p>
            );
          })}
          {data.moverCause.whyNotConfirmedJa && (
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-faint)' }}>
              確定できない理由: {data.moverCause.whyNotConfirmedJa}
            </p>
          )}
          {(data.moverCause.nextChecksJa ?? []).length > 0 && (
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-sub)' }}>
              次に確認: {(data.moverCause.nextChecksJa ?? []).join(' / ')}
            </p>
          )}
          {data.moverCause.freshness?.isStale && (
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--amber, #fbbf24)' }}>
              ⚠ 原因候補の鮮度低下 — {data.moverCause.freshness.staleReasonJa}
            </p>
          )}
          {marketConfLineJa(data.moverCause) && (
            <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-sub)' }}>
              {marketConfLineJa(data.moverCause)}
            </p>
          )}
          {(freshnessLineJa(data.moverCause) || data.moverCause.checkedJa) && (
            <p style={{ margin: '2px 0 0', fontSize: 11, color: 'var(--text-faint)' }}>
              {[freshnessLineJa(data.moverCause), data.moverCause.checkedJa && `確認済み: ${data.moverCause.checkedJa}`]
                .filter(Boolean).join(' · ')}
            </p>
          )}
        </div>
      ) : (
        <div className="csc-trigger">
          <span className="csc-k">確定した即時引き金</span>
          {data.immediateTrigger ? (
            <span className="csc-trigger-v">{CAUSE_JA[data.immediateTrigger.cause] ?? data.immediateTrigger.cause}（信頼度 {Math.round(data.immediateTrigger.confidence * 100)}%）</span>
          ) : (
            <span className="csc-trigger-none">確認できず（断定しない）</span>
          )}
        </div>
      )}

      <div className="csc-causes">
        <span className="csc-k">推定原因の分布</span>
        {causes.map(([c, p]) => (
          <div className="csc-cause" key={c}>
            <span className={`csc-cause-name${c === 'UNKNOWN' ? ' csc-cause-name--unknown' : ''}`}>{CAUSE_JA[c] ?? c}</span>
            <span className="csc-bar"><i style={{ width: `${Math.round(p * 100)}%` }} className={c === 'UNKNOWN' ? 'csc-bar--unknown' : ''} /></span>
            <span className="csc-pct">{Math.round(p * 100)}%</span>
          </div>
        ))}
      </div>

      <div className="csc-grid">
        <div><span className="csc-k">波及範囲</span><span className="csc-v">{SCOPE_JA[data.contagion?.scope] ?? data.contagion?.scope ?? '—'}{data.contagion?.peersTotal ? `（${data.contagion.peersDown}/${data.contagion.peersTotal}銘柄）` : ''}</span></div>
        {posTop && <div><span className="csc-k">需給(高速)</span><span className="csc-v">{POS_JA[posTop[0]] ?? posTop[0]} {Math.round(posTop[1] * 100)}% <span className="csc-dim">・投資家特定は不可</span></span></div>}
        <div><span className="csc-k">未確認の割合</span><span className="csc-v">{Math.round((data.unknownShare || 0) * 100)}%</span></div>
        {data.preEvent?.preEventDeRiskingProbability >= 0.4 && (
          <div><span className="csc-k">決算前手仕舞い</span><span className="csc-v">{Math.round(data.preEvent.preEventDeRiskingProbability * 100)}%（結果は未確定）</span></div>
        )}
      </div>

      {/* v11.6.0: compact institutional notes — public signals, context only */}
      {(data.institutionalSignals ?? []).length > 0 && (
        <div style={{ borderLeft: '2px solid var(--line)', paddingLeft: 8, margin: '6px 0' }}>
          <span className="csc-k">INSTITUTIONAL SIGNAL</span>
          {(data.institutionalSignals ?? []).map((s) => (
            <div key={s.id} style={{ marginTop: 2 }}>
              <p style={{ margin: 0, fontSize: 12, color: 'var(--text-sub)' }}>
                <b>{s.sourceName}</b>
                <span style={{ marginLeft: 6, color: s.stance === 'bullish' ? 'var(--value-positive)'
                  : s.stance === 'bearish' ? 'var(--value-negative)' : 'var(--amber, #fbbf24)' }}>
                  {s.stanceJa}
                </span>
                <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
                  {s.directnessJa}{s.headlineOnly ? ' · 見出しのみ(限定確度)' : ''}
                </span>
              </p>
              <p style={{ margin: '1px 0 0', fontSize: 11.5, color: 'var(--text-sub)' }}>{s.displayTitleJa || s.headline}</p>
              <p style={{ margin: '1px 0 0', fontSize: 11, color: 'var(--text-faint)', lineHeight: 1.6 }}>
                {s.ownerReadableWhy}
              </p>
            </div>
          ))}
          <p style={{ margin: '3px 0 0', fontSize: 9.5, color: 'var(--text-faint)' }}>
            公開シグナル(文脈情報)・売買指示ではありません
          </p>
        </div>
      )}

      {/* v11.7.0: flow attribution — 誰の売買か(推定)。実測/推定を分離、断定なし */}
      {data.flowAttribution && data.flowAttribution.flowClass !== 'unknown' && (
        <div style={{ borderLeft: '2px solid var(--line)', paddingLeft: 8, margin: '6px 0' }}>
          <span className="csc-k">FLOW (推定)</span>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-sub)' }}>
            <b>{data.flowAttribution.flowClassJa}</b>
            <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-faint)' }}>
              {data.flowAttribution.directnessJa} · 確度{Math.round(data.flowAttribution.confidence * 100)}%
            </span>
          </p>
          <p style={{ margin: '1px 0 0', fontSize: 11, color: 'var(--text-faint)', lineHeight: 1.6 }}>
            {data.flowAttribution.ownerReadableWhyJa}
          </p>
          {data.flowAttribution.missingEvidence.length > 0 && data.flowAttribution.confidence < 0.65 && (
            <p style={{ margin: '1px 0 0', fontSize: 10, color: 'var(--text-faint)' }}>
              足りない証拠: {data.flowAttribution.missingEvidence.slice(0, 3).join(' / ')}
            </p>
          )}
        </div>
      )}

      <p className="csc-next"><b>何が変われば結論が変わるか:</b> {data.preEvent?.nextEvidenceRequired}</p>
      {data.dataLimitations?.length > 0 && (
        <p className="csc-limits">データ制約: {data.dataLimitations.join(' / ')}</p>
      )}
      {(() => {
        // v11.5.4 No Stale News: current list = fresh/recent only (each with its age);
        // stale keeps a caveat; old lives ONLY under collapsed 過去ニュース, and >7d old
        // stays hidden until the user expands. No current news → 最新ニュース未取得.
        const all = data.news ?? [];
        const isPast = (n: (typeof all)[number]) =>
          n.newsFreshness?.freshness === 'old' || n.newsFreshness?.freshness === 'stale';
        // v11.5.6 owner rule: newest at the top in BOTH lists (undated sinks last)
        const byAge = (a: (typeof all)[number], b: (typeof all)[number]) => {
          const ha = a.newsFreshness?.ageHours ?? null;
          const hb = b.newsFreshness?.ageHours ?? null;
          if (ha == null && hb == null) return 0;
          if (ha == null) return 1;
          if (hb == null) return -1;
          return ha - hb;
        };
        const current = all.filter((n) => !isPast(n)).sort(byAge);
        const past = all.filter(isPast).sort(byAge);
        const renderRow = (n: (typeof all)[number], i: number, dim: boolean) => {
          const pending = n.translationStatus === 'pending' || n.translationStatus === 'failed';
          const original = n.titleOriginal;
          const ageH = n.newsFreshness?.ageHours;
          const ageLabel = ageH == null ? '' : ageH < 1 ? '1h以内' : ageH < 24 ? `${Math.floor(ageH)}h前` : `${Math.floor(ageH / 24)}日前`;
          return (
            <div className="csc-news-row" key={i} style={dim ? { opacity: 0.55 } : undefined}>
              <span className={`csc-news-cls csc-news-cls--${n.cls}`}>
                {dim ? '過去材料' : (NEWS_CLS_JA[n.cls] ?? n.cls)}</span>
              <span className="csc-news-title">
                {newsDisplayTitleJa(n)}
                {ageLabel && <span className="csc-dim" style={{ marginLeft: 6, fontSize: 10 }}>{ageLabel}</span>}
                {pending && <span className="csc-dim" style={{ marginLeft: 6, fontSize: 10 }}>{newsRequested ? '翻訳リクエスト済み' : '翻訳取得中'}</span>}
                {n.assoc?.relationJa && <span className="csc-news-assoc">連想: {n.assoc.relationJa}</span>}
                {pending && original && (
                  <details style={{ display: 'inline' }}>
                    <summary style={{ display: 'inline', cursor: 'pointer', fontSize: 10, color: 'var(--text-faint)', marginLeft: 6 }}>原文を見る</summary>
                    <span style={{ color: 'var(--text-faint)', fontSize: 11 }}> {original}</span>
                  </details>
                )}
              </span>
              <span className="csc-news-meta">{[n.source, n.time].filter(Boolean).join(' · ')}</span>
            </div>
          );
        };
        if (all.length === 0) return null;
        return (
          <div className="csc-news">
            <div className="csc-news-h">NEWS<span className="csc-dim"> · 関連ニュース(直近24時間)</span></div>
            {current.slice(0, 5).map((n, i) => renderRow(n, i, false))}
            {current.length === 0 && (
              <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-faint)' }}>最新ニュース未取得</p>
            )}
            {past.length > 0 && (
              <details style={{ marginTop: 4 }}>
                <summary style={{ cursor: 'pointer', fontSize: 11, color: 'var(--text-faint)' }}>
                  過去ニュース({past.length}件) — 現在材料ではありません
                </summary>
                {past.slice(0, 5).map((n, i) => renderRow(n, i + 100, true))}
              </details>
            )}
          </div>
        );
      })()}
      </>)}
      <p className="csc-foot">決定支援のみ・原因の断定や機関名の名指しはしません。</p>
    </section>
  );
};
