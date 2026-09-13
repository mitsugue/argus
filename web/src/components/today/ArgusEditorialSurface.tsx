import React from 'react';
import type { MarketBrief } from '../../lib/marketBrief';
import { hasEditorialIntent, editorialElementLabel } from '../../lib/presentationIntent';
import { validJapanMarketComparison } from '../../lib/japanMarketComparison';
import { JapanMarketComparisonChart } from '../chart/JapanMarketComparisonChart';
import { OwnerDialogue } from '../dialogue/OwnerDialogue';
import { MarketAnalysisHistory } from './MarketAnalysisHistory';
import './ArgusEditorialSurface.css';

const labels = { view: 'ARGUSの今日の見立て', reasons: 'そう考える理由', changes: '前回から変わったこと',
  impact: '自分の銘柄への影響', next: '次に確かめたいこと', invalidation: '見方を変える条件' };
type Section = keyof typeof labels;

export function ArgusEditorialSurface({ brief, updateState, retained = false }: { brief: MarketBrief; updateState?: React.ReactNode; retained?: boolean }) {
  if (!hasEditorialIntent(brief)) return null;
  const plan = brief.presentationPlan!; const summary = brief.unifiedSummary!;
  const chart = brief.calculationSnapshots?.['5']?.comparison;
  const at = brief.aiDiagnostics?.completedAt ?? brief.generatedAt;
  const hasChart = plan.elements.some(row => row.id === 'nikkei-comparison');
  return <section className="argus-editorial" aria-label="ARGUSの今日の見立て"
    data-argus-contract="presentation-intent-v1" data-presentation-id={plan.planId} data-context-id={plan.contextId}>
    <header className="argus-editorial__edition"><span>Today / 日本市場</span>
      <time dateTime={at}>{new Date(at).toLocaleString('ja-JP', { timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 更新</time></header>
    <p className="argus-editorial__period">日経平均 · 5営業日先まで</p>
    {updateState}
    {retained && <p role="status" className="argus-editorial__retained">今の説明を更新できていません。前回の説明と、その時点のチャートを表示しています。</p>}
    {plan.elements.map(choice => {
      const source = brief.presentationCatalog!.elements.find(row => row.id === choice.id)!;
      const className = `argus-editorial__element is-${choice.emphasis} placement-${choice.placement} element-${choice.id}`;
      if (choice.id === 'nikkei-comparison') return validJapanMarketComparison(chart, 5)
        ? <div className={className} key={choice.id} data-payload-id={source.payloadId}>
          <JapanMarketComparisonChart document={chart} />
          {!retained && <OwnerDialogue symbol="N225" market="JP" horizon={5} baseContextId={plan.contextId} />}
        </div> : null;
      const evidenceLabel = editorialElementLabel(choice.id);
      if (evidenceLabel && choice.caption) {
        const facts = (brief.unifiedContext?.facts ?? []).filter(f => source.evidenceIds.includes(f.evidenceId));
        const content = <><p className="argus-editorial__text">{choice.caption.textJa}</p>
          {choice.caption.kind === 'UNKNOWN' && <small className="argus-editorial__uncertain">確認できていない範囲を含みます</small>}
          <details className="argus-editorial__fact-list"><summary>使った情報・数値・時点を見る</summary>
            {facts.map(f => <div key={f.evidenceId} data-evidence-id={f.evidenceId}>
              <p>{f.text}</p><small>{f.provenance?.sourceLabel ?? f.source}
                {f.provenance?.observedAt && ` · 観測 ${f.provenance.observedAt}`}
                {f.provenance?.publishedAt && ` · 公表 ${f.provenance.publishedAt}`}
                {f.provenance?.receivedAt && ` · 取得 ${f.provenance.receivedAt}`}</small>
              {f.provenance?.url && <a href={f.provenance.url} target="_blank" rel="noopener noreferrer">出典を開く</a>}
            </div>)}
          </details></>;
        return choice.placement === 'detail'
          ? <details className={className} key={choice.id} data-payload-id={source.payloadId}><summary>{evidenceLabel}</summary>{content}</details>
          : <section className={className} key={choice.id} aria-label={evidenceLabel} data-payload-id={source.payloadId}><h2>{evidenceLabel}</h2>{content}</section>;
      }
      const key = choice.id as Section; const row = summary.sections[key];
      const content = <><p className="argus-editorial__text">{row.textJa}</p>
        {row.kind === 'UNKNOWN' && <small className="argus-editorial__uncertain">確認できていない範囲</small>}</>;
      return choice.placement === 'detail'
        ? <details className={className} key={key} data-payload-id={source.payloadId}><summary>{labels[key]}</summary>{content}</details>
        : <section className={className} key={key} aria-label={labels[key]} data-payload-id={source.payloadId}>
          <h2>{labels[key]}</h2>{content}</section>;
    })}
    {!hasChart && !retained && <OwnerDialogue symbol="N225" market="JP" horizon={5} baseContextId={plan.contextId} />}
    <details className="argus-editorial__evidence"><summary>説明の根拠と、今回の構成について</summary>
      <p>{plan.intentJa}</p>
      {plan.elements.map(choice => <p key={choice.id}><b>{labels[choice.id as Section] ?? editorialElementLabel(choice.id) ?? '比較チャート'}：</b>{choice.purposeJa}</p>)}
      {Object.entries(summary.sections).map(([key, row]) => <section key={key}><h3>{labels[key as Section]}</h3>
        <p>{row.kind === 'FACT' ? '確認した事実' : row.kind === 'INFERENCE' ? '根拠に基づく推論' : '未確認'}</p>
        {row.evidenceIds.map(id => {
          const fact = [...(brief.unifiedContext?.facts ?? []), ...(brief.unifiedContext?.previousFacts ?? [])].find(f => f.evidenceId === id);
          return fact ? <p key={id}>{fact.text}<small>{fact.provenance?.sourceLabel ?? fact.source} · 公表 {fact.provenance?.publishedAt ?? '時刻未確認'}</small>
            {fact.provenance?.url && <a href={fact.provenance.url} target="_blank" rel="noopener noreferrer">出典</a>}</p> : null;
        })}</section>)}
      <p>応答モデル {brief.aiDiagnostics?.returnedModel ?? '未確認'} · 保存 {brief.analysisHistory?.status === 'LOCAL_DURABLE' ? 'サーバー保存済み' : '確認中'}</p>
    </details>
    <MarketAnalysisHistory key="saved-history" />
  </section>;
}
