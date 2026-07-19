import React from 'react';
import type { DeskCardData } from './types';
import { PRIMARY_EN, linkedTagJa, fmtPrice, freshnessOf } from './deskFormat';
import { SIGNALS, resolveSignal, OVERRIDE_LABEL_JA, type OwnerState, type SignalCode } from '../../domain/actionLevel';
import { SignalGauge } from '../action/SignalGauge';
import { SignedValue } from '../common/SignedValue';
import { RANK_TONE as AP_TONE } from '../../domain/actionPriority';
import { bestAssetName } from '../../lib/assetStrategy';

// V12.2.12 — 閉じたカード(§6): 開かなくても「何をどうするか」が分かる1枚。
// 主判断はdomain/assetDecisionの出力のみ(AI PRIMARY / RULE TEMPORARY明示)。

const HP_COLOR: Record<string, string> = { red: '#F87171', amber: '#FBBF24', green: '#34D399', neutral: 'var(--text-sub)' };
const GENRE_TAG: Record<string, string> = { jp: 'JP', us: 'US', funds: '投信', crypto: 'CRYPTO' };

export function deskSignalCode(d: DeskCardData): SignalCode {
  if (d.card) return d.card.signalCode;
  const sig = resolveSignal(d.strat.action, {
    downsideOverride: d.incident?.actionOverride,
    dataQuality: d.strat.status === 'live' ? 'LIVE' : d.strat.status === 'mock' ? 'MOCK' : 'PARTIAL',
    materialDownside: !!d.incident,
    ownerState: (d.incident?.ownerState as OwnerState) || undefined,
  });
  return sig.code;
}

export const AssetDecisionSummary: React.FC<{
  d: DeskCardData; open: boolean; onToggle: () => void;
}> = ({ d, open, onToggle }) => {
  const code = deskSignalCode(d);
  const sigColor = `var(${SIGNALS[code].token})`;
  const name = bestAssetName(d.asset, d.liveName ?? d.card?.name);
  const held = !!(d.pn?.held || d.card?.held || (d.asset.quantity ?? 0) > 0);
  const priceShown = d.strat.status === 'mock' ? null : (d.strat.price ?? d.card?.price);
  const chgShown = d.strat.status === 'mock' ? null : (d.strat.changePct ?? d.card?.changePct);
  const fresh = freshnessOf(d.strat);
  const conf = d.decision?.confidencePct ?? (d.strat.confidence != null ? Math.round(d.strat.confidence * 100) : null);
  const reason1 = d.decision?.reasonJa && d.decision.reasonJa !== '判断根拠を取得中'
    ? d.decision.reasonJa : (d.card?.causeOneLineJa || d.strat.reasonJa);
  const nextCond = d.decision?.rule.nextConditionJa || d.strat.nextConditionJa || null;
  // 警告は最大2(それ以上は展開で) — incident override > 保有者向け注意 > ownerState
  const warns: { textJa: string; tone: string }[] = [];
  if (d.incident) {
    warns.push({ textJa: `⚠ ${OVERRIDE_LABEL_JA[d.incident.actionOverride] ?? d.incident.actionOverride}`,
      tone: ['EXIT_WATCH', 'TRIM_WATCH'].includes(d.incident.actionOverride) ? '#F87171' : '#FBBF24' });
  }
  if (d.hp && d.hp.tone !== 'neutral' && d.hp.tone !== 'green') {
    warns.push({ textJa: `保有: ${d.hp.labelJa}`, tone: HP_COLOR[d.hp.tone] });
  }
  if (warns.length < 2 && d.incident?.ownerState && d.incident.ownerState !== 'watch') {
    warns.push({ textJa: d.incident.ownerState, tone: '#FBBF24' });
  }

  return (
    <button className="ad-head" onClick={onToggle} aria-expanded={open}
      aria-label={`${d.asset.symbol} ${name}, ${PRIMARY_EN[code]}`}>
      <span className="ad-l1">
        {held ? <span className="ad-held">保有</span> : <span className="ad-watch">WATCH</span>}
        <span className="ad-sym">{d.asset.symbol}</span>
        <span className="ad-name">{name}</span>
        <span className="ad-mkt">{GENRE_TAG[d.genre]}</span>
        <span className="ad-price">{fmtPrice(d.asset.market, priceShown)}</span>
        <span className="ad-chg">{chgShown == null ? '—' : <SignedValue value={chgShown} suffix="%" arrow={false} />}</span>
        <span className="ad-fresh" style={{ color: fresh.color }}>{fresh.text}</span>
        {(d.card?.lastUpdate || d.strat.date) && (
          <span className="ad-asof">as of {d.card?.lastUpdate ?? d.strat.date}</span>
        )}
      </span>
      <span className="ad-l2">
        <span className="ad-cmd" style={{ color: sigColor }}>{PRIMARY_EN[code]}</span>
        <SignalGauge code={code} />
        {d.decision ? (
          <span className={`ad-src ad-src--${d.decision.judgmentSource}`}
                title={d.decision.sourceDetailJa}>
            {d.decision.sourceTagEn}
          </span>
        ) : (
          <span className="ad-src ad-src--rule" title="この資産クラスはルールエンジンのみ(AI判定対象外)">RULE</span>
        )}
        {conf != null && <span className="ad-meta">確度{conf}%</span>}
        {d.strat.risk !== '—' && <span className="ad-meta">risk {d.strat.risk}</span>}
        {d.apx && d.apx.priorityRank !== 'Ignore' && (
          <span className="ad-prio" style={{ color: AP_TONE[d.apx.priorityRank] }}>{d.apx.priorityRank}</span>
        )}
      </span>
      {reason1 && <span className="ad-reason">{reason1}</span>}
      <span className="ad-foot">
        {nextCond && <span className="ad-next">次の確認: {nextCond}</span>}
        {warns.slice(0, 2).map((w) => (
          <span key={w.textJa} className="ad-warn" style={{ color: w.tone }}>{w.textJa}</span>
        ))}
        {d.eventTags.slice(0, 2).map((le, index) => (
          <span key={`${le.code}:${le.countdown}:${index}`} className="ad-event" title="関連イベント">{linkedTagJa(le)}</span>
        ))}
      </span>
    </button>
  );
};
