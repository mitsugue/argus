// V11.19.1 — Mutual Fund / FIRE Core Tracker (device-local TS port of
// argus_fire_core.py). オーナー方針:「投資信託の合計額をFIRE用の本丸資産として
// 扱います。個別株の利益は、将来的にこのFIRE Coreへ移す候補として見ます。」
// 投信の詳細(口数・評価額・積立額・口座区分)は端末内+暗号化バックアップのみ。
// NAV捏造なし・リアルタイム不要(日次/手動更新)・証券会社連携なし。

import type { AssetItem } from '../types/assetItem';
import type { PortfolioExposure } from '../domain/positionExposure';
import type { LocalAssetRole } from '../domain/portfolioStrategy';

export const FIRE_CORE_KEY = 'argus.fireCore.v1';
const STALE_DAYS = 10;  // v12.0.7: 週1程度(7〜9日間隔)の手動更新を過剰警告しない(Py側と同期)
export const OWNER_RULE_JA = '投資信託の合計額をFIRE用の本丸資産として扱います。個別株の利益は、将来的にこのFIRE Coreへ移す候補として見ます。';

export type AccountType = 'nisa' | 'ideco' | 'taxable' | 'corporate' | 'unknown';
export const ACCOUNT_JA: Record<AccountType, string> = {
  nisa: 'NISA', ideco: 'iDeCo', taxable: '特定/一般', corporate: '法人', unknown: '未設定',
};
export type RatioBand = 'ok' | 'elevated' | 'stretched' | 'exceeded' | 'unknown';
export const RATIO_BAND_JA: Record<RatioBand, string> = {
  ok: '許容内', elevated: 'やや大きめ', stretched: '大きい', exceeded: '超過', unknown: '判定保留',
};

export interface FundMeta {
  accountType?: AccountType;
  monthlyContribution?: number | null;
  contributionDay?: number | null;
  manualValue?: number | null;       // 現在評価額の手動入力(円)
  manualValueDate?: string | null;   // YYYY-MM-DD
  ownerNote?: string;
}

function loadMeta(): Record<string, FundMeta> {
  try { return JSON.parse(localStorage.getItem(FIRE_CORE_KEY) || '{}') as Record<string, FundMeta>; }
  catch { return {}; }
}
export function fundMeta(symbol: string): FundMeta { return loadMeta()[symbol.toUpperCase()] ?? {}; }
export function saveFundMeta(symbol: string, patch: Partial<FundMeta>): void {
  const all = loadMeta();
  all[symbol.toUpperCase()] = { ...all[symbol.toUpperCase()], ...patch };
  try { localStorage.setItem(FIRE_CORE_KEY, JSON.stringify(all)); } catch { /* quota */ }
}

export interface LocalFundPosition {
  symbol: string; fundName: string;
  accountType: AccountType; accountTypeJa: string;
  marketValue: number | null;          // units×NAV(自動) or 手動評価額
  valueSource: 'units_x_nav' | 'manual_value' | 'missing';
  unrealizedPnlPct: number | null;     // コスト不明ならnull(捏造しない)
  monthlyContribution: number | null;
  stale: boolean | null;
  lastValueDate: string | null;
}

export interface LocalFireCore {
  positions: LocalFundPosition[];
  mutualFundTotal: number | null;
  fireCoreTotal: number | null;
  monthlyContributionTotal: number | null;
  fireCoreShare: number | null;        // 既知資産に対する%
  tacticalTotal: number | null;
  tacticalToCoreRatio: number | null;
  tacticalToCoreBand: RatioBand;
  satelliteToCoreRatio: number | null;
  contributionDataStatus: 'complete' | 'partial' | 'missing' | 'unknown';
  valuationDataStatus: 'current' | 'stale' | 'manual' | 'missing' | 'unknown';
  staleCount: number;
  summaryJa: string;
  warningsJa: string[];
  opportunitiesJa: string[];
  missingDataJa: string[];
}

const jstToday = () => new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);
const daysBetween = (a: string, b: string) =>
  Math.round((Date.parse(b) - Date.parse(a)) / 86_400_000);

export function buildLocalFireCore(assets: AssetItem[], pe: PortfolioExposure,
  roles: LocalAssetRole[]): LocalFireCore {
  const meta = loadMeta();
  const holdBySym = new Map(pe.base.holdings.map((h) => [h.symbol.toUpperCase(), h]));
  const today = jstToday();

  const funds = assets.filter((a) => (a.assetType === 'core_fund' || a.assetType === 'manual_fund'));
  const positions: LocalFundPosition[] = funds.map((a) => {
    const sym = a.symbol.toUpperCase();
    const m = meta[sym] ?? {};
    const h = holdBySym.get(sym);           // units×NAV(既存の日次NAV追跡・捏造なし)
    let value: number | null = null;
    let src: LocalFundPosition['valueSource'] = 'missing';
    let stale: boolean | null = null;
    let dateStr: string | null = null;
    if (h) {
      value = h.value; src = 'units_x_nav'; stale = false; dateStr = today;   // NAVは日次取得
    } else if (m.manualValue != null && m.manualValue > 0) {
      value = m.manualValue; src = 'manual_value';
      dateStr = m.manualValueDate ?? null;
      stale = dateStr ? daysBetween(dateStr, today) > STALE_DAYS : null;
    }
    return {
      symbol: sym, fundName: a.displayNameJa || a.displayName,
      accountType: m.accountType ?? 'unknown',
      accountTypeJa: ACCOUNT_JA[m.accountType ?? 'unknown'],
      marketValue: value, valueSource: src,
      unrealizedPnlPct: h ? Math.round(h.plPct * 10) / 10 : null,
      monthlyContribution: m.monthlyContribution ?? null,
      stale, lastValueDate: dateStr,
    };
  });

  const valued = positions.filter((p) => p.marketValue != null);
  const mfTotal = valued.length ? valued.reduce((s, p) => s + (p.marketValue ?? 0), 0) : null;
  const fireCoreTotal = mfTotal;      // 長期コアETFの明示マークは将来対応(捏造しない)

  const knownContribs = positions.filter((p) => p.monthlyContribution != null);
  const monthly = knownContribs.length
    ? knownContribs.reduce((s, p) => s + (p.monthlyContribution ?? 0), 0) : null;
  const contribStatus = !positions.length ? 'unknown'
    : knownContribs.length === positions.length ? 'complete'
      : knownContribs.length ? 'partial' : 'missing';

  const staleCount = positions.filter((p) => p.stale === true).length;
  const valuationStatus = !positions.length ? 'unknown'
    : !valued.length ? 'missing'
      : staleCount ? 'stale'
        : valued.some((p) => p.valueSource === 'manual_value') ? 'manual' : 'current';

  // 戦術枠/サテライトの円換算合計(役割×比率×既知総額)
  const combined = pe.base.combinedJpy;
  const rolePct = (r: string) => roles.filter((x) => x.role === r)
    .reduce((s, x) => s + (x.weightPct ?? 0), 0);
  const tacticalTotal = combined != null ? Math.round(combined * rolePct('tactical') / 100) : null;
  const satelliteTotal = combined != null ? Math.round(combined * rolePct('satellite') / 100) : null;

  const ratio = (x: number | null): [number | null, RatioBand] => {
    if (x == null || fireCoreTotal == null) return [null, x != null && fireCoreTotal == null ? 'unknown' : 'unknown'];
    if (fireCoreTotal <= 0) return [null, x > 0 ? 'exceeded' : 'unknown'];
    const r = Math.round(x / fireCoreTotal * 100) / 100;
    return [r, r <= 0.3 ? 'ok' : r <= 0.6 ? 'elevated' : r <= 1.0 ? 'stretched' : 'exceeded'];
  };
  const [tacRatio, tacBand] = ratio(tacticalTotal);
  const [satRatio] = ratio(satelliteTotal);

  const totalKnown = (fireCoreTotal ?? 0) + (combined != null
    ? Math.round(combined * (rolePct('tactical') + rolePct('satellite') + rolePct('hedge')) / 100) : 0);
  const share = fireCoreTotal != null && totalKnown > 0
    ? Math.round(fireCoreTotal / totalKnown * 1000) / 10 : null;

  const warningsJa = [
    ...(tacBand === 'stretched' || tacBand === 'exceeded'
      ? ['戦術枠がFIRE Coreに対して大きくなっています。個別株の勝負がFIRE計画全体を振らす構成です。'] : []),
    ...(staleCount ? [`FIRE Coreの評価額が未更新です(${staleCount}件が${STALE_DAYS}日超)。投資信託の現在価値を更新すると、戦術枠の取りすぎを正確に判定できます。`] : []),
    ...(valuationStatus === 'missing' ? ['投資信託の評価額が未入力のため、FIRE Coreを判定できません。'] : []),
    ...(contribStatus === 'missing' && positions.length ? ['毎月積立額が未入力のため、長期入金整合は判定保留です。'] : []),
  ].slice(0, 4);

  const summaryJa = fireCoreTotal == null
    ? 'FIRE Core(投資信託)の評価額が未入力です。Watchlistで投信の口数を入力するか、下の欄で現在評価額を手動入力してください。'
    : `${share != null ? `FIRE Core合計は既知資産の${share.toFixed(0)}%です。` : ''}${tacRatio != null ? `戦術枠/FIRE Core比は${tacRatio.toFixed(2)}(${RATIO_BAND_JA[tacBand]})。` : ''}投資信託はFIREの本丸資産として追跡中です。`;

  return {
    positions, mutualFundTotal: mfTotal, fireCoreTotal,
    monthlyContributionTotal: monthly, fireCoreShare: share,
    tacticalTotal, tacticalToCoreRatio: tacRatio, tacticalToCoreBand: tacBand,
    satelliteToCoreRatio: satRatio,
    contributionDataStatus: contribStatus, valuationDataStatus: valuationStatus,
    staleCount, summaryJa, warningsJa,
    opportunitiesJa: [
      ...(['elevated', 'stretched', 'exceeded'].includes(tacBand) && fireCoreTotal != null
        ? ['個別株の利益が出た場合、一定部分をFIRE Coreへ移す検討余地があります。'] : []),
      ...(contribStatus === 'complete'
        ? ['積立額が登録済みです。継続していれば長期側の土台は機能します(将来見込みの精密計算はしません)。'] : []),
    ].slice(0, 2),
    missingDataJa: [
      ...(valuationStatus === 'missing' ? ['投信の評価額(口数入力 or 手動評価額)'] : []),
      ...(contribStatus !== 'complete' && positions.length ? ['毎月積立額'] : []),
      ...(positions.some((p) => p.accountType === 'unknown') ? ['口座区分(NISA/iDeCo等)'] : []),
    ].slice(0, 3),
  };
}

/** Today用 — 出すべきFIRE Core注意があれば1行(なければnull)。 */
export function fireCoreTodayNoteJa(f: LocalFireCore | null):
{ tone: string; textJa: string } | null {
  if (!f || !f.positions.length) return null;
  if (f.valuationDataStatus === 'stale') {
    return { tone: 'var(--amber, #fbbf24)', textJa: 'FIRE Coreの評価額が未更新です。投資信託の現在価値を更新すると、戦術枠の取りすぎを正確に判定できます。' };
  }
  if (f.valuationDataStatus === 'missing') {
    return { tone: 'var(--amber, #fbbf24)', textJa: 'FIRE Core(投資信託)の評価額が未入力です。Positions & Risk→FIRE COREで入力できます。' };
  }
  if (f.tacticalToCoreBand === 'stretched' || f.tacticalToCoreBand === 'exceeded') {
    return { tone: 'var(--value-negative)', textJa: `FIRE Core注意: 戦術枠がFIRE Coreの${(f.tacticalToCoreRatio ?? 0).toFixed(1)}倍に達しています。個別株の追加より本丸(投信)側の確認が先です。` };
  }
  return null;
}

/** Pro Handoff / AI Review — device-local FIRE Core lines. */
export function fcHandoffTextJa(f: LocalFireCore | null): string {
  if (!f || !f.positions.length) return '';
  const L = ['## FIRE Core / Mutual Funds (device-local, 手動/日次更新・助言ではない)'];
  L.push(f.summaryJa);
  L.push(`積立状況: ${f.contributionDataStatus === 'complete' ? '全ファンド登録済み' : f.contributionDataStatus === 'partial' ? '一部未入力' : '未入力'} / 評価額: ${f.valuationDataStatus}`);
  for (const w of f.warningsJa.slice(0, 3)) L.push(`- 警告: ${w}`);
  for (const o of f.opportunitiesJa) L.push(`- 機会: ${o}`);
  if (f.missingDataJa.length) L.push(`不足データ: ${f.missingDataJa.join(' / ')}`);
  L.push('注意: 評価額は日次NAVまたは手動入力であり、リアルタイムではない。数値は端末内のみ。');
  return L.join('\n');
}
