import type { AssetItem } from '../types/assetItem';
import type { AssetStrategy } from './assetStrategy';
import type { DownsideIncident } from '../hooks/useDownsideIncidents';

// Position-aware guidance for assets you actually HOLD (quantity entered), v10.113.
// Combines unrealized P/L (computed on-device from quantity+avgCost — never sent
// anywhere) with the rule action + any downside incident, into a holder posture:
// 損切り / 一部利確 / 我慢 / ナンピン / 買い増し / 保持.
//
// i18n reconstruction (v10.127): this is the canonical "frontend reconstruction"
// pattern — the function returns a structured key + params and BUILDS both en and
// ja text from them (no backend prose, no per-string translation table). Switching
// locale is a pure re-render, never a network/AI call.
//
// Decision-SUPPORT only: phrased as 検討/候補/慎重に (consider/candidate/cautious),
// never a command, and ARGUS never auto-trades. The owner decides.

export type HolderTone = 'red' | 'amber' | 'green' | 'neutral';

export interface HolderPosture {
  key: string;
  tone: HolderTone;
  plPct: number | null;
  labelEn: string;
  labelJa: string;
  reasonEn: string;
  reasonJa: string;
}

function fmtPl(pl: number | null): string {
  if (pl == null) return '';
  const s = pl >= 0 ? '+' : '−';
  return `${s}${Math.abs(pl).toFixed(1)}%`;
}

interface Built {
  key: string; tone: HolderTone;
  labelEn: string; labelJa: string;
  reasonEn: string; reasonJa: string;
}
function mk(b: Built, plPct: number | null): HolderPosture {
  return { ...b, plPct };
}

export function holderPosture(
  asset: AssetItem,
  strat: AssetStrategy,
  incident?: DownsideIncident | null,
): HolderPosture | null {
  const qty = asset.quantity ?? 0;
  if (qty <= 0) return null;                       // only for real positions

  const avg = asset.avgCost;
  const price = strat.price;
  const plPct = (typeof avg === 'number' && avg > 0 && typeof price === 'number')
    ? ((price - avg) / avg) * 100 : null;
  const pl = fmtPl(plPct);
  // bilingual P/L pieces
  const gainJa = plPct != null ? `含み${plPct >= 0 ? '益' : '損'}${pl}` : '';
  const gainEn = plPct != null ? `unrealized ${plPct >= 0 ? 'gain' : 'loss'} ${pl}` : '';
  const plNoteJa = plPct != null ? `(${gainJa})` : '(取得単価未入力)';
  const plNoteEn = plPct != null ? `(${gainEn})` : '(avg cost not entered)';

  const action = strat.action;
  const ovr = incident?.actionOverride;
  const itype = incident?.incidentType;
  const sev = incident?.severity;
  const badNews = itype === 'STOCK_SPECIFIC_BAD_NEWS';
  const unknown = itype === 'CAUSE_UNKNOWN_DOWNSIDE';
  const marketWide = itype === 'MARKET_WIDE_SELL_OFF';
  const down = plPct != null && plPct < 0;
  const deepDown = plPct != null && plPct <= -10;

  // 1) 損切り検討 — clear bearish signal (confirmed) + a real loss.
  if ((ovr === 'EXIT_WATCH' || action === 'EXIT' || (sev === 'critical' && badNews)) && down) {
    return mk({
      key: 'cut', tone: 'red', labelEn: 'Consider cutting loss', labelJa: '損切り検討',
      reasonJa: `明確な弱気シグナル${badNews ? '(個別の悪材料)' : ''}+${gainJa}。損切りラインを点検(自動売買はしません・最終判断はご自身で)。`,
      reasonEn: `Clear bearish signal${badNews ? ' (stock-specific bad news)' : ''} + ${gainEn}. Review your stop-loss line (no auto-trading — you decide).`,
    }, plPct);
  }
  // 2) 一部縮小 — held + override says don't just sit.
  if (ovr === 'TRIM_WATCH') {
    return mk({
      key: 'trim', tone: 'amber', labelEn: 'Consider trimming', labelJa: '一部縮小を検討',
      reasonJa: `大口の売り等で戻りが弱い兆候。戻り局面での一部縮小も選択肢。${plNoteJa}`,
      reasonEn: `Weak rebound (e.g. large selling). Trimming into strength is one option. ${plNoteEn}`,
    }, plPct);
  }
  if (ovr === 'REVIEW_REQUIRED' || ovr === 'DO_NOT_ADD') {
    return mk({
      key: 'review', tone: 'amber', labelEn: 'Review (don\'t over-hold)', labelJa: '要点検(我慢しすぎ注意)',
      reasonJa: `原因${unknown ? '未確認' : '確認中'}の下落。通常の「保持」で放置せず点検。買い増しは控える。${plNoteJa}`,
      reasonEn: `Drop with cause ${unknown ? 'unconfirmed' : 'under review'}. Don't just sit on a plain "hold" — review. Avoid adding. ${plNoteEn}`,
    }, plPct);
  }
  // 3) 一部利確検討 — large gain + overheat/trim.
  if (action === 'TRIM' || (plPct != null && plPct >= 20 && (action === 'WAIT' || incident))) {
    return mk({
      key: 'takeprofit', tone: 'amber', labelEn: 'Consider taking some profit', labelJa: '一部利確を検討',
      reasonJa: `${gainJa}。過熱/利確シグナル。利益の一部確定も選択肢(全売り推奨ではない)。`,
      reasonEn: `${gainEn}. Overheated / take-profit signal. Locking in part of the gain is an option (not a full-sell call).`,
    }, plPct);
  }
  // 4) 買い増し候補 — explicit add signal.
  if (action === 'ADD') {
    return mk({
      key: 'add', tone: 'green', labelEn: 'Add candidate', labelJa: '買い増し候補',
      reasonJa: `買い増しシグナル。${down ? `${gainJa}だが、` : ''}計画内で段階的に。`,
      reasonEn: `Add signal. ${down ? `${gainEn}, but ` : ''}scale in gradually within your plan.`,
    }, plPct);
  }
  // 5) ナンピン — dip-buy signal on a losing position (cautious by default).
  if (action === 'BUY_DIP' && down) {
    if (unknown || badNews) {
      return mk({
        key: 'avg_cautious', tone: 'amber', labelEn: 'Average down — be cautious', labelJa: 'ナンピンは慎重に',
        reasonJa: `押し目だが原因${unknown ? '未確認' : '=悪材料'}。ナンピンは見送り、原因/下げ止まりの確認を推奨。${gainJa}。`,
        reasonEn: `A dip, but cause ${unknown ? 'unconfirmed' : 'is bad news'}. Hold off on averaging down; confirm the cause / a bottom first. ${gainEn}.`,
      }, plPct);
    }
    return mk({
      key: 'avg', tone: 'green', labelEn: 'Average-down candidate (cautious)', labelJa: 'ナンピン候補(慎重)',
      reasonJa: `押し目シグナル+悪材料は未確認。ナンピンは分割・少額で慎重に。${gainJa}。`,
      reasonEn: `Dip signal + no confirmed bad news. Average down only in small, split lots. ${gainEn}.`,
    }, plPct);
  }
  // 6) 我慢(様子見) — holding through a benign drawdown.
  if (down && (action === 'HOLD' || action === 'WAIT')) {
    const causeJa = marketWide ? '地合い主導の下げ' : incident ? '一時的な下げ' : '短期の下げ';
    const causeEn = marketWide ? 'a market-wide drop' : incident ? 'a temporary drop' : 'a short-term drop';
    return mk({
      key: 'endure', tone: 'neutral', labelEn: 'Endure (watch & keep holding)', labelJa: '我慢(様子見・継続保持)',
      reasonJa: `${causeJa}で、保有継続が妥当。${deepDown ? '含み損が深いので損切りラインだけは事前に決めておく。' : ''}${gainJa}。下げ止まり/反転を確認。`,
      reasonEn: `${causeEn} — holding is reasonable. ${deepDown ? 'The loss is deep, so set a stop-loss line in advance. ' : ''}${gainEn}. Watch for a bottom / reversal.`,
    }, plPct);
  }
  // 7) 保持(継続) — default.
  return mk({
    key: 'hold', tone: 'green', labelEn: 'Keep holding', labelJa: '保持(継続)',
    reasonJa: `${plPct != null && plPct >= 0 ? `${gainJa}。` : ''}方針通り継続保持。`,
    reasonEn: `${plPct != null && plPct >= 0 ? `${gainEn}. ` : ''}Keep holding per plan.`,
  }, plPct);
}
