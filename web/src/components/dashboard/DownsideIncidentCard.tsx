import React from 'react';
import { jpIntradayJa } from '../../lib/regimeLabels';
import { useDownsideIncidents, type DownsideIncident } from '../../hooks/useDownsideIncidents';
import { OVERRIDE_LABEL_JA } from '../../domain/actionLevel';
import './DownsideIncidentCard.css';

// Downside Incident Response card (v10.98). Renders only when there is an active
// incident or a JP intraday overlay that differs from the global regime — so on a
// calm day it stays out of the way. Decision-support only; no order controls.

const OVERRIDE_JA = OVERRIDE_LABEL_JA;
const CAUSE_JA: Record<string, string> = {
  MARKET_WIDE_SELL_OFF: '市場全体の下げ', SECTOR_SELL_OFF: 'セクターの下げ',
  THEME_PROFIT_TAKING: 'テーマ利確', STOCK_SPECIFIC_BAD_NEWS: '個別の悪材料',
  FLOW_DISTRIBUTION: '大口の売り', SHORT_COVER_EXHAUSTION: '踏み上げ一巡',
  POST_RALLY_PROFIT_TAKING: '急騰後の利確', TECHNICAL_BREAKDOWN: 'テクニカル崩れ',
  CAUSE_UNKNOWN_DOWNSIDE: '原因未確認', DATA_QUALITY_LIMITED: 'データ不足',
};

function overrideTone(o: string): 'red' | 'amber' {
  return o === 'EXIT_WATCH' || o === 'TRIM_WATCH' ? 'red' : 'amber';
}
function sevTone(s: string): 'red' | 'amber' | 'gray' {
  if (s === 'critical' || s === 'high') return 'red';
  if (s === 'medium') return 'amber';
  return 'gray';
}

export const IncidentRow: React.FC<{ inc: DownsideIncident }> = ({ inc }) => {
  const [open, setOpen] = React.useState(false);
  const pct = typeof inc.changePct === 'number' ? `${inc.changePct.toFixed(1)}%` : '—';
  const top = inc.causeBuckets?.[0];
  return (
    <div className={`dic-row dic-row--${sevTone(inc.severity)}`}>
      <button className="dic-row__head" onClick={() => setOpen((v) => !v)}>
        <div className="dic-row__id">
          {inc.isHeld && <span className="dic-held">保有</span>}
          <span className="dic-sym">{inc.symbol}</span>
          <span className="dic-name">{inc.assetName}</span>
        </div>
        <div className="dic-row__nums">
          <span className="dic-pct">{pct}</span>
          <span className={`dic-ovr dic-ovr--${overrideTone(inc.actionOverride)}`}>
            {OVERRIDE_JA[inc.actionOverride] ?? inc.actionOverride}
          </span>
        </div>
      </button>
      <div className="dic-overrideline">
        <span className="dic-lbl">Rule: {inc.currentAction}</span>
        <span className="dic-arrow">→</span>
        <span className="dic-lbl dic-lbl--ovr">Override: {inc.actionOverride}</span>
        {top && (
          <span className="dic-why">
            {CAUSE_JA[top.cause] ?? top.cause} {Math.round(top.probability * 100)}%
          </span>
        )}
        {inc.caosLead && (
          <span className={`dic-caos dic-caos--${inc.caosLead.corroboration}`} title={inc.caosLead.relationJa || undefined}>
            C.A.O.S.{inc.caosLead.via === 'entity' ? '·連想' : ''}
          </span>
        )}
      </div>
      <p className="dic-reason">{inc.reasonJa}</p>
      {open && (
        <div className="dic-detail">
          <div className="dic-buckets">
            {inc.causeBuckets.slice(0, 4).map((b) => (
              <div className="dic-bucket" key={b.cause}>
                <span className="dic-bucket__name">{CAUSE_JA[b.cause] ?? b.cause}</span>
                <span className="dic-bucket__bar"><i style={{ width: `${Math.round(b.probability * 100)}%` }} /></span>
                <span className="dic-bucket__pct">{Math.round(b.probability * 100)}%</span>
              </div>
            ))}
          </div>
          <p className="dic-line"><b>やってはいけない:</b> {inc.doNotDoJa}</p>
          <p className="dic-line"><b>次の確認条件:</b> {inc.nextConditionJa}</p>
          {inc.missingData.length > 0 && (
            <p className="dic-line dic-missing"><b>欠損データ:</b> {inc.missingData.join(' / ')}</p>
          )}
        </div>
      )}
    </div>
  );
};

export const DownsideIncidentCard: React.FC = () => {
  const { data } = useDownsideIncidents();
  if (!data) return null;
  const incidents = data.incidents ?? [];
  const overlayActive = data.jpIntradayOverlay && data.jpIntradayOverlay !== 'NORMAL';
  if (incidents.length === 0 && !overlayActive) return null;

  return (
    <section className="dic-card">
      <header className="dic-card__head">
        <h2>Downside Watch <span className="dic-jp">急落の理由と対応</span></h2>
        {overlayActive && (
          <span className={`dic-overlay dic-overlay--${data.jpIntradayOverlay === 'RISK_OFF_WATCH' ? 'red' : 'amber'}`}>
            日本ザラ場: {jpIntradayJa(data.jpIntradayOverlay)}
          </span>
        )}
      </header>
      {overlayActive && <p className="dic-overlay-reason">{data.overlay?.reasonJa}</p>}
      {data.holderRiskOverlay === 'REVIEW_REQUIRED' && (
        <p className="dic-holder">保有銘柄が影響を受けています。通常のHOLDとして扱わず点検してください。</p>
      )}
      {incidents.map((inc) => <IncidentRow key={inc.incidentId} inc={inc} />)}
      {incidents.length === 0 && (
        <p className="dic-reason">個別のインシデントはまだ無いが、日本市場の地合いが弱含み。新規追加は慎重に。</p>
      )}
      <p className="dic-foot">決定支援のみ・自動売買は行いません。最終判断はご自身で。</p>
    </section>
  );
};
