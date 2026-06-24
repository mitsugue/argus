import type { AssetItem } from '../types/assetItem';
import type { AssetStrategy } from './assetStrategy';
import type { DownsideIncident } from '../hooks/useDownsideIncidents';

// Position-aware guidance for assets you actually HOLD (quantity entered), v10.113.
// Combines unrealized P/L (computed on-device from quantity+avgCost — never sent
// anywhere) with the rule action + any downside incident, into a Japanese holder
// posture: 損切り / 一部利確 / 我慢 / ナンピン / 買い増し / 保持.
//
// Decision-SUPPORT only: phrased as 検討/候補/慎重に, never a command, and ARGUS
// never auto-trades. The owner decides.

export type HolderTone = 'red' | 'amber' | 'green' | 'neutral';

export interface HolderPosture {
  key: string;
  labelJa: string;
  tone: HolderTone;
  reasonJa: string;
  plPct: number | null;
}

function fmtPl(pl: number | null): string {
  if (pl == null) return '';
  const s = pl >= 0 ? '+' : '−';
  return `${s}${Math.abs(pl).toFixed(1)}%`;
}

function mk(key: string, labelJa: string, tone: HolderTone, reasonJa: string, plPct: number | null): HolderPosture {
  return { key, labelJa, tone, reasonJa, plPct };
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
  const plNote = plPct != null ? `(含み${plPct >= 0 ? '益' : '損'}${pl})` : '(取得単価未入力)';

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
    return mk('cut', '損切り検討', 'red',
      `明確な弱気シグナル${badNews ? '(個別の悪材料)' : ''}+含み損${pl}。損切りラインを点検(自動売買はしません・最終判断はご自身で)。`, plPct);
  }
  // 2) 要点検 / 一部縮小 — held + override says don't just sit.
  if (ovr === 'TRIM_WATCH') {
    return mk('trim', '一部縮小を検討', 'amber',
      `大口の売り等で戻りが弱い兆候。戻り局面での一部縮小も選択肢。${plNote}`, plPct);
  }
  if (ovr === 'REVIEW_REQUIRED' || ovr === 'DO_NOT_ADD') {
    return mk('review', '要点検(我慢しすぎ注意)', 'amber',
      `原因${unknown ? '未確認' : '確認中'}の下落。通常の「保持」で放置せず点検。買い増しは控える。${plNote}`, plPct);
  }
  // 3) 一部利確検討 — large gain + overheat/trim.
  if (action === 'TRIM' || (plPct != null && plPct >= 20 && (action === 'WAIT' || incident))) {
    return mk('takeprofit', '一部利確を検討', 'amber',
      `含み益${pl}。過熱/利確シグナル。利益の一部確定も選択肢(全売り推奨ではない)。`, plPct);
  }
  // 4) 買い増し候補 — explicit add signal.
  if (action === 'ADD') {
    return mk('add', '買い増し候補', 'green',
      `買い増しシグナル。${down ? `含み損${pl}だが、` : ''}計画内で段階的に。`, plPct);
  }
  // 5) ナンピン — dip-buy signal on a losing position (cautious by default).
  if (action === 'BUY_DIP' && down) {
    if (unknown || badNews) {
      return mk('avg_cautious', 'ナンピンは慎重に', 'amber',
        `押し目だが原因${unknown ? '未確認' : '=悪材料'}。ナンピンは見送り、原因/下げ止まりの確認を推奨。含み損${pl}。`, plPct);
    }
    return mk('avg', 'ナンピン候補(慎重)', 'green',
      `押し目シグナル+悪材料は未確認。ナンピンは分割・少額で慎重に。含み損${pl}。`, plPct);
  }
  // 6) 我慢(様子見) — holding through a benign drawdown.
  if (down && (action === 'HOLD' || action === 'WAIT')) {
    const causeJa = marketWide ? '地合い主導の下げ' : incident ? '一時的な下げ' : '短期の下げ';
    return mk('endure', '我慢(様子見・継続保持)', 'neutral',
      `${causeJa}で、保有継続が妥当。${deepDown ? '含み損が深いので損切りラインだけは事前に決めておく。' : ''}含み損${pl}。下げ止まり/反転を確認。`, plPct);
  }
  // 7) 保持(継続) — default.
  return mk('hold', '保持(継続)', 'green',
    `${plPct != null && plPct >= 0 ? `含み益${pl}。` : ''}方針通り継続保持。`, plPct);
}
