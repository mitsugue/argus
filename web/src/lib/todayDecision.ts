/**
 * Plain-language decision strip for the Today page (owner request 2026-10-02:
 * fewer words, a coloured conclusion, numbers that matter for multi-day
 * Nikkei ETF trades, and "so what" next to every input).
 *
 * Everything here is deterministic arithmetic on values the brief already
 * carries. Directions are the conventional reading of each input, not a
 * validated forecast; only the drop alert and the expected range were checked
 * out of sample (2003-2014 design, 2015-2026 report; see docs below).
 */
import type { ComparisonPoint } from '../types/japanMarketComparison';

export type Lean = 'tail' | 'head' | 'soft-head' | 'neutral';
export interface FeatureRow { seriesId: string; date: string; value: number }
export interface MaterialRow { id: string; lean: Lean; title: string; meaning: string;
  what: string; now: string; soWhat: string }
export interface DecisionStrip {
  close: number | null; dayChangePct: number | null; fiveDayChangePct: number | null;
  sigma: number | null; alert: 'low' | 'normal' | 'high' | null;
  band: { lower: number; upper: number } | null;
  momentum: 'strong' | 'normal' | 'weak' | null;
  rows: MaterialRow[]; tone: 'tail' | 'head' | 'wait';
}

/** Drop-alert cut points and the 80% band multipliers fitted on 2003-2014 only.
 *  2015-2026 out of sample: a fall of 5% or more within 5 sessions happened on
 *  2.9% / 9.1% / 16.7% of low / normal / high days; 81% of outcomes fell inside the band. */
export const ALERT_LOW_BELOW = 0.1473;
export const ALERT_HIGH_FROM = 0.2608;
export const ALERT_HISTORY = { low: 2.9, normal: 9.1, high: 16.7 } as const;
const BAND_LOWER = 1.278; const BAND_UPPER = 1.371;

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);

/** Annualised volatility of the last 20 session returns of the actual path. */
export function realisedVol20(actual: ComparisonPoint[]): number | null {
  const pts = [...actual].filter(p => finite(p.value) && finite(p.offsetSessions) && p.offsetSessions <= 0)
    .sort((a, b) => a.offsetSessions - b.offsetSessions).slice(-21);
  if (pts.length < 21) return null;
  const r = pts.slice(1).map((p, i) => p.value / pts[i].value - 1);
  const mean = r.reduce((a, b) => a + b, 0) / r.length;
  const variance = r.reduce((a, b) => a + (b - mean) ** 2, 0) / (r.length - 1);
  return Math.sqrt(variance) * Math.sqrt(250);
}

export function alertLevel(sigma: number): 'low' | 'normal' | 'high' {
  return sigma < ALERT_LOW_BELOW ? 'low' : sigma >= ALERT_HIGH_FROM ? 'high' : 'normal';
}

/** Central 80% band of the 5-session return, in percent. */
export function fiveDayBand(sigma: number) {
  const s5 = sigma * Math.sqrt(5 / 250);
  return { lower: -BAND_LOWER * s5 * 100, upper: BAND_UPPER * s5 * 100 };
}

const oku = (yen: number) => `${Math.round(Math.abs(yen) / 1e8).toLocaleString('ja-JP')}億円`;
const pct = (v: number, digits = 1) => `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;

/** One row per input the owner can act on; absent inputs are simply left out. */
export function materialRows(features: FeatureRow[], fiveDayChangePct: number | null): MaterialRow[] {
  const f = (id: string) => features.find(row => row.seriesId === id && finite(row.value))?.value;
  const rows: MaterialRow[] = [];
  const foreign = f('foreign_flow.net4w');
  if (foreign !== undefined) rows.push({ id: 'foreign', lean: foreign < 0 ? 'head' : 'tail',
    title: `海外投資家 4週で約${oku(foreign)}の${foreign < 0 ? '売り越し' : '買い越し'}`,
    meaning: foreign < 0 ? '相場を動かす主役が売り側。上値を追う力は弱め。' : '相場を動かす主役が買い側。下値は支えられやすい。',
    what: '日本株の売買の約6〜7割を占める海外投資家が、直近4週で買ったか売ったかの合計です。',
    now: `${foreign < 0 ? '売り' : '買い'}が約${oku(foreign)}上回っています。`,
    soWhat: foreign < 0 ? '大きく買い上がる力は出にくい状態です。' : '押し目で買いが入りやすい状態です。' });
  const us10 = f('rate.us10y_change5');
  if (us10 !== undefined && Math.abs(us10) >= 0.1) rows.push({ id: 'us10y', lean: us10 > 0 ? 'head' : 'tail',
    title: `米国10年金利 5日で${us10 > 0 ? '+' : ''}${us10.toFixed(2)}ポイント`,
    meaning: us10 > 0 ? '金利が上がると株は割高に見えやすい。' : '金利が下がると株の割高感は和らぐ。',
    what: '世界のお金の値段の基準になる米国の長期金利です。',
    now: `直近5営業日で${us10 > 0 ? '上昇' : '低下'}しています。`,
    soWhat: us10 > 0 ? 'ハイテク・半導体株を中心に重しになりやすい状態です。' : '株にとっては追い風になりやすい状態です。' });
  const m1570 = f('margin1570.ratio');
  if (m1570 !== undefined) rows.push({ id: 'm1570', lean: m1570 >= 1 ? 'soft-head' : 'tail',
    title: `日経レバの信用倍率 ${m1570.toFixed(1)}倍(${m1570 >= 1 ? '買いが多い' : '売りが多い'})`,
    meaning: m1570 >= 1 ? '上がった所で利益確定の売りが出やすい。' : '下がった所で買い戻しが入りやすい。',
    what: '日経平均の2倍型ETF(1570)を、借金で買っている量÷借りて売っている量です。',
    now: `買い残が売り残の${m1570.toFixed(1)}倍です。`,
    soWhat: m1570 >= 1 ? '上昇しても売りに押されやすく、勢いが続きにくい状態です。' : '売り方の買い戻しが上昇の燃料になりうる状態です。' });
  const vixChange = f('vix.change5'); const vix = f('vix.level');
  if (vix !== undefined) rows.push({ id: 'vix', lean: vix >= 25 || (vixChange ?? 0) >= 3 ? 'head' : vix < 15 ? 'tail' : 'neutral',
    title: `米国の恐怖指数(VIX) ${vix.toFixed(1)}${vixChange !== undefined ? `(5日で${vixChange > 0 ? '+' : ''}${vixChange.toFixed(1)})` : ''}`,
    meaning: vix >= 25 ? '市場は大きな値動きを警戒している。' : vix < 15 ? '市場は落ち着いている。' : '警戒はふつうの水準。',
    what: '米国株がこの先どれだけ動くと市場が見込んでいるかを表す指数です。20前後が平常です。',
    now: `${vix.toFixed(1)}です。`,
    soWhat: vix >= 25 ? '日経も大きく振れやすく、持つ量を控えめにする局面です。' : '値動きの大きさはふつうか小さめです。' });
  const fx = f('fx.usdjpy_change5');
  if (fx !== undefined && Math.abs(fx) >= 1) rows.push({ id: 'fx', lean: fx > 0 ? 'tail' : 'head',
    title: `ドル円 5日で${pct(fx)}(${fx > 0 ? '円安' : '円高'})`,
    meaning: fx > 0 ? '輸出企業の利益が増えやすい。' : '輸出企業の利益が目減りしやすい。',
    what: '1ドルが何円かの動きです。日経平均は輸出企業の比重が大きく、円安で上がりやすい傾向があります。',
    now: `${fx > 0 ? '円安' : '円高'}方向に動いています。`, soWhat: fx > 0 ? '日経には追い風です。' : '日経には逆風です。' });
  if (fiveDayChangePct !== null) rows.push({ id: 'trend', lean: fiveDayChangePct >= 1.5 ? 'tail' : fiveDayChangePct <= -1.5 ? 'head' : 'neutral',
    title: `日経平均の勢い 5日で${pct(fiveDayChangePct)}`,
    meaning: fiveDayChangePct >= 1.5 ? '上昇の流れが続いている。' : fiveDayChangePct <= -1.5 ? '下落の流れが続いている。' : '方向感は小さい。',
    what: '直近5営業日の日経平均の騰落率です。',
    now: `${pct(fiveDayChangePct)}です。`, soWhat: '流れの向きの確認用で、この先を当てる指標ではありません。' });
  const sq = f('event.sq_sessions');
  if (sq !== undefined && sq <= 5) rows.push({ id: 'sq', lean: 'neutral',
    title: `SQ(先物・オプションの清算日)まであと${Math.round(sq)}営業日`,
    meaning: 'SQの週は先物主導で値動きが荒くなりやすい。',
    what: '毎月第2金曜日に先物・オプションが清算される日です。3・6・9・12月は特に大きい。',
    now: `あと${Math.round(sq)}営業日です。`, soWhat: '週半ばから値動きが荒くなる可能性を見込んでおく局面です。' });
  return rows;
}

export function decisionStrip(actual: ComparisonPoint[] | null, features: FeatureRow[]): DecisionStrip {
  const sorted = (actual ?? []).filter(p => finite(p.value) && p.offsetSessions <= 0)
    .sort((a, b) => a.offsetSessions - b.offsetSessions);
  const at = (o: number) => sorted.find(p => p.offsetSessions === o)?.value;
  const last = at(0), prev = at(-1), five = at(-5);
  const dayChangePct = last && prev ? (last / prev - 1) * 100 : null;
  const fiveDayChangePct = last && five ? (last / five - 1) * 100 : null;
  const rv = realisedVol20(sorted);
  const vix = features.find(row => row.seriesId === 'vix.level' && finite(row.value))?.value;
  const sigma = rv !== null && vix !== undefined ? (vix / 100 + rv) / 2 : null;
  let momentum: DecisionStrip['momentum'] = null;
  const window = sorted.slice(-20).map(p => p.value);
  if (window.length === 20 && last) {
    const mean = window.reduce((a, b) => a + b, 0) / 20;
    const sd = Math.sqrt(window.reduce((a, b) => a + (b - mean) ** 2, 0) / 19);
    const z = sd > 0 ? (last - mean) / sd : 0;
    momentum = z >= 1.8 ? 'strong' : z <= -1.8 ? 'weak' : 'normal';
  }
  const rows = materialRows(features, fiveDayChangePct);
  const score = rows.reduce((s, r) => s + (r.lean === 'tail' ? 1 : r.lean === 'head' ? -1 : r.lean === 'soft-head' ? -0.5 : 0), 0);
  return { close: last ?? null, dayChangePct, fiveDayChangePct, sigma,
    alert: sigma === null ? null : alertLevel(sigma), band: sigma === null ? null : fiveDayBand(sigma), momentum,
    rows, tone: score >= 1.5 ? 'tail' : score <= -1.5 ? 'head' : 'wait' };
}

/** Feature facts arrive as long machine sentences; show the number the way a person reads it. */
export function friendlyFactText(text: string): string {
  const cleaned = text.replace(/観測値からの記述計算であり、予測力は未検証。?/g, '').trim();
  return cleaned.replace(/(-?\d{9,}(?:\.\d+)?)/g, raw => {
    const v = Number(raw); return Number.isFinite(v) ? `${v < 0 ? '-' : ''}${oku(v)}` : raw;
  }).replace(/(\d+\.\d{3,})/g, raw => String(Number(Number(raw).toFixed(2))));
}
