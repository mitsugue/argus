import React from 'react';
import { jpIntradayJa } from '../../lib/regimeLabels';
import {
  useDownsideIncidents, type DownsideIncident, type DownsideSnapshot,
  type MoverCauseCompact,
} from '../../hooks/useDownsideIncidents';
import { probabilityDisplay } from '../../domain/decisionView';
import { AiExplanationBlock } from './AiExplanationBlock';
import './DownsideIncidentCard.css';

// v11.3.4 — freshness + market-confirmation one-liners shared by the cause blocks.
export function freshnessLineJa(mc?: MoverCauseCompact): string | null {
  const fr = mc?.freshness;
  if (!fr?.lastEvidenceRefreshAt) return null;
  const ageMin = Math.round((fr.evidenceAgeSec ?? 0) / 60);
  const next = fr.nextAutoCheckAt
    ? new Date(fr.nextAutoCheckAt).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
    : '—';
  return `最終確認 ${ageMin}分前 · 次回自動確認 ${next}`;
}
export function marketConfLineJa(mc?: MoverCauseCompact): string | null {
  const m = mc?.marketConfirmation;
  if (!m?.status || m.status === 'missing') return null;
  const parts: string[] = [];
  if (typeof m.volumeRatio === 'number') parts.push(`出来高比 x${m.volumeRatio.toFixed(1)}`);
  if (typeof m.relativeToIndexPct === 'number') parts.push(`指数相対 ${m.relativeToIndexPct >= 0 ? '+' : ''}${m.relativeToIndexPct.toFixed(1)}%`);
  if (typeof m.peerBasketMovePct === 'number') parts.push(`同業 ${m.peerBasketMovePct >= 0 ? '+' : ''}${m.peerBasketMovePct.toFixed(1)}%`);
  if (typeof m.vwapDistancePct === 'number') parts.push(`VWAP比 ${m.vwapDistancePct >= 0 ? '+' : ''}${m.vwapDistancePct.toFixed(1)}%`);
  if (parts.length === 0) return null;
  const label = m.status === 'confirmed' ? '市場確認' : m.status === 'partial' ? '市場確認(一部)' : '市場確認対象外';
  return `${label}: ${parts.join(' · ')}${m.stale ? '(45分以上前の計算・確定には使わない)' : ''}`;
}

// Downside Incident Response card (v10.98). Renders only when there is an active
// incident or a JP intraday overlay that differs from the global regime — so on a
// calm day it stays out of the way. Decision-support only; no order controls.

// Legacy actionOverride is intentionally translated into risk evidence, never an
// action label. The canonical owner-aware action is rendered only by SDA surfaces.
const OVERRIDE_RISK_EVIDENCE_JA: Record<string, string> = {
  HOLD_CAUTION: '保有影響の警戒証拠', WAIT: '不確実性の証拠',
  DO_NOT_ADD: '追加リスクの証拠', REVIEW_REQUIRED: '要精査の証拠',
  TRIM_WATCH: '高い下方リスク証拠', EXIT_WATCH: '重大な下方リスク証拠',
};
const CAUSE_JA: Record<string, string> = {
  MARKET_WIDE_SELL_OFF: '市場全体の下げ', SECTOR_SELL_OFF: 'セクターの下げ',
  THEME_PROFIT_TAKING: 'テーマ利確', STOCK_SPECIFIC_BAD_NEWS: '個別の悪材料',
  FLOW_DISTRIBUTION: '大口の売り', SHORT_COVER_EXHAUSTION: '踏み上げ一巡',
  POST_RALLY_PROFIT_TAKING: '急騰後の利確', TECHNICAL_BREAKDOWN: 'テクニカル崩れ',
  CAUSE_UNKNOWN_DOWNSIDE: '原因未確認', DATA_QUALITY_LIMITED: 'データ不足',
};

// Mover Cause ladder chip (v11.3.3): 原因確定と候補を分離 — never a bare 原因未確認.
const LADDER_TONE: Record<string, string> = {
  confirmed_cause: 'var(--value-negative, #f87171)',
  probable_catalyst: 'var(--amber, #fbbf24)',
  candidate_catalyst: 'var(--text-sub)',
  no_lead_yet: 'var(--text-faint)',
  not_scoreable: 'var(--text-faint)',
};

function overrideTone(o: string): 'red' | 'amber' {
  return o === 'EXIT_WATCH' || o === 'TRIM_WATCH' ? 'red' : 'amber';
}
function sevTone(s: string): 'red' | 'amber' | 'gray' {
  if (s === 'critical' || s === 'high') return 'red';
  if (s === 'medium') return 'amber';
  return 'gray';
}

export const IncidentRow: React.FC<{
  inc: DownsideIncident;
  onFocus?: (symbol: string, section: 'evidence') => void;
}> = ({ inc, onFocus }) => {
  const [open, setOpen] = React.useState(false);
  const pct = typeof inc.changePct === 'number' ? `${inc.changePct.toFixed(1)}%` : '—';
  const top = inc.causeBuckets?.[0];
  const cause = inc.moverCause?.causeStatusJa
    || (top ? `${CAUSE_JA[top.cause] ?? top.cause}候補` : '原因確認中');
  const next = inc.moverCause?.nextChecksJa?.[0] || inc.nextConditionJa;
  return (
    <div className={`dic-row dic-row--${sevTone(inc.severity)}`}>
      <button className="dic-row__head" onClick={() => onFocus?.(inc.symbol, 'evidence')}>
        <div className="dic-row__id">
          {inc.isHeld && <span className="dic-held">保有</span>}
          <span className="dic-sym">{inc.symbol}</span>
          <span className="dic-name">{inc.assetName}</span>
        </div>
        <div className="dic-row__nums">
          <span className="dic-pct">{pct}</span>
          <span className={`dic-ovr dic-ovr--${overrideTone(inc.actionOverride)}`}>
            {OVERRIDE_RISK_EVIDENCE_JA[inc.actionOverride] ?? '分類未確定の下方リスク証拠'}
          </span>
        </div>
      </button>
      <div className="dic-row__decision">
        <span style={{ color: LADDER_TONE[inc.moverCause?.causeStatus ?? ''] || 'var(--text-sub)' }}>
          {cause}
        </span>
        <span>次：{next}</span>
        <button type="button" className="dic-evidence" aria-expanded={open}
                onClick={() => setOpen((value) => !value)}>
          {open ? '証拠を閉じる' : '証拠'}
        </button>
      </div>
      {open && (
        <div className="dic-detail">
          <p className="dic-line"><b>RISK EVIDENCE:</b>{' '}
            {OVERRIDE_RISK_EVIDENCE_JA[inc.actionOverride] ?? '分類未確定の下方リスク証拠'}
            （SDAのPrimary Actionを上書きしません）</p>
          <p className="dic-line"><b>要約:</b> {inc.reasonJa}</p>
          <div className="dic-buckets">
            {inc.causeBuckets.slice(0, 4).map((b) => (
              <div className="dic-bucket" key={b.cause}>
                <span className="dic-bucket__name">{CAUSE_JA[b.cause] ?? b.cause}</span>
                <span className="dic-bucket__pct">
                  {probabilityDisplay(b.probability * 100).qualitative}
                </span>
              </div>
            ))}
          </div>
          {inc.moverCause && (
            <div className="dic-line" style={{ borderLeft: '2px solid var(--line)', paddingLeft: 8, margin: '6px 0' }}>
              {inc.moverCause.bestLeadJa && <p className="dic-line" style={{ margin: 0 }}><b>最有力:</b> {inc.moverCause.bestLeadJa}</p>}
              {(inc.moverCause.topCandidates ?? [])
                .filter((c) => !c.titleJa || !(inc.moverCause?.bestLeadJa || '').includes(c.titleJa))
                .slice(0, 2).map((c, i) => (
                <p className="dic-line" style={{ margin: 0, color: 'var(--text-sub)' }} key={i}>
                  ・{c.titleJa} <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>
                    ({c.timingRelation === 'after_move' ? '値動き後' : c.timingRelation === 'before_move' ? '値動き前' : c.timingRelation === 'during_move' ? '値動き中' : '時刻未確認'}
                    ・{c.corroborationLevel === 'official' ? '公式' : c.corroborationLevel === 'multi_source' ? '複数ソース' : c.corroborationLevel === 'market_confirmed' ? '市場確認' : c.corroborationLevel === 'single_source' ? '単一ソース' : '未裏取り'})
                  </span>
                </p>
              ))}
              {inc.moverCause.whyNotConfirmedJa && (
                <p className="dic-line dic-missing" style={{ margin: 0 }}><b>確定できない理由:</b> {inc.moverCause.whyNotConfirmedJa}</p>
              )}
              {(inc.moverCause.nextChecksJa ?? []).length > 0 && (
                <p className="dic-line" style={{ margin: 0 }}><b>次に確認:</b> {(inc.moverCause.nextChecksJa ?? []).join(' / ')}</p>
              )}
              {inc.moverCause.freshness?.isStale && (
                <p className="dic-line" style={{ margin: 0, color: 'var(--amber, #fbbf24)' }}>
                  ⚠ 原因候補の鮮度低下 — {inc.moverCause.freshness.staleReasonJa}
                </p>
              )}
              {marketConfLineJa(inc.moverCause) && (
                <p className="dic-line" style={{ margin: 0 }}>{marketConfLineJa(inc.moverCause)}</p>
              )}
              <AiExplanationBlock
                explanationJa={inc.moverCause?.explanationJa}
                explanationStatus={inc.moverCause?.explanationStatus}
                symbol={inc.symbol}
                market={inc.market}
                context="downside-card"
                dense
              />
              {(freshnessLineJa(inc.moverCause) || inc.moverCause.checkedJa) && (
                <p className="dic-line" style={{ margin: 0, color: 'var(--text-faint)', fontSize: 11 }}>
                  {[freshnessLineJa(inc.moverCause), inc.moverCause.checkedJa && `確認済み: ${inc.moverCause.checkedJa}`]
                    .filter(Boolean).join(' · ')}
                </p>
              )}
            </div>
          )}
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
  return <DownsideIncidentQueue data={data} />;
};

export const DownsideIncidentQueue: React.FC<{
  data: DownsideSnapshot | null;
  maxItems?: number;
  onFocus?: (symbol: string, section: 'evidence') => void;
}> = ({ data, maxItems = 4, onFocus }) => {
  if (!data) return null;
  const incidents = data.incidents ?? [];
  const overlayActive = data.jpIntradayOverlay && data.jpIntradayOverlay !== 'NORMAL';
  if (incidents.length === 0 && !overlayActive) return null;

  return (
    <section className="dic-card" data-authority-role="EVIDENCE_ONLY">
      <header className="dic-card__head">
        <h2>Downside Watch <span className="dic-jp">急落の理由とリスク証拠</span></h2>
        {overlayActive && (
          <span className={`dic-overlay dic-overlay--${data.jpIntradayOverlay === 'RISK_OFF_WATCH' ? 'red' : 'amber'}`}>
            日本ザラ場: {jpIntradayJa(data.jpIntradayOverlay)}
          </span>
        )}
      </header>
      {overlayActive && <p className="dic-overlay-reason">{data.overlay?.reasonJa}</p>}
      {data.holderRiskOverlay === 'REVIEW_REQUIRED' && (
        <p className="dic-holder">保有影響のリスク証拠が検出されています。最終判断の再評価材料として点検してください。</p>
      )}
      {incidents.slice(0, maxItems).map((inc) => (
        <IncidentRow key={inc.incidentId} inc={inc} onFocus={onFocus} />
      ))}
      {incidents.length > maxItems && (
        <p className="dic-more">ほか {incidents.length - maxItems}件は資産一覧で確認</p>
      )}
      {incidents.length === 0 && (
        <p className="dic-reason">個別のインシデントはまだ無いが、日本市場の弱含みをリスク証拠として表示中。</p>
      )}
      <p className="dic-foot">EVIDENCE ONLY · 最終判断（PRIMARY ACTION）を上書きしません。自動売買なし。</p>
    </section>
  );
};
