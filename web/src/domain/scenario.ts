// V11.17.0 — Scenario Engine (device-local TS port of argus_scenario.py).
// 「明日どうなる?」に単一予測で答えず、証拠から組んだ条件付きの分岐(ベース/
// 強気/弱気/踏み上げ→失速/イベント待ち)+無効化条件+次の確認で答える。
// 確率は帯のみ(%断定は実証モデルなしには絶対にしない)。売買指示ではない。
// 保有文脈(isHeld)は端末内でのみ合成され、外に出ない。

import { jpDisplay } from '../lib/displayName';

export type ScenarioLabel = 'base' | 'bullish' | 'bearish' | 'squeeze_then_fade' | 'wait_event';
export type Dominant = 'bullish' | 'base' | 'bearish' | 'mixed' | 'wait_event' | 'unknown';
export type Band = 'high' | 'medium' | 'low' | 'unknown';

export const BAND_JA: Record<Band, string> = {
  high: '優勢', medium: '中程度', low: '成立条件付き', unknown: '判定保留',
};
export const DOM_JA: Record<Dominant, string> = {
  bullish: '強気優勢(条件付き)', base: 'ベース優勢', bearish: '弱気優勢',
  mixed: '強弱拮抗', wait_event: 'イベント待ち', unknown: '判定保留',
};
export const DOM_TONE: Record<Dominant, string> = {
  bullish: 'var(--value-positive)', base: 'var(--text-sub)',
  bearish: 'var(--value-negative)', mixed: 'var(--amber, #fbbf24)',
  wait_event: 'var(--event-medium)', unknown: 'var(--text-faint)',
};
export const COMPLIANCE_JA = '条件付きシナリオであり予測でも売買指示でもない。';

export interface ScenarioInputs {
  symbol: string; market: string; assetName: string;
  isHeld: boolean;
  sdRank?: string | null; sdCondition?: string | null;
  sdLevel?: string | null; sdDirection?: string | null;
  flowClass?: string | null; instStance?: string | null;
  eventPending?: boolean; eventName?: string | null;
  regimeRiskOff?: boolean; changePct?: number | null; priorRunupPct?: number | null;
  positionRiskLevel?: string | null;
  missing?: string[];
}

export interface ScenarioCase {
  label: ScenarioLabel; titleJa: string; narrativeJa: string;
  band: Band; bandJa: string; conditionsJa: string[]; actionJa: string;
}

export interface LocalScenarioSet {
  symbol: string; assetName: string; isHeld: boolean;
  dominant: Dominant; dominantJa: string;
  summaryJa: string; cases: ScenarioCase[];
  nextChecksJa: string[]; invalidationJa: string[]; whatWouldChangeJa: string[];
  evidenceQuality: 'strong' | 'medium' | 'weak' | 'insufficient';
}

export function buildScenarioSet(i: ScenarioInputs): LocalScenarioSet {
  const disp = jpDisplay(i.symbol, i.assetName);
  const sdRank = i.sdRank ?? '', sdCond = i.sdCondition ?? '', flow = i.flowClass ?? '';
  const heavy = i.sdLevel === 'heavy' || i.sdLevel === 'very_heavy';
  const squeeze = sdCond === 'squeeze_prone' || flow === 'short_covering';
  const improvingHeavy = sdCond === 'improving_but_heavy';
  const event = !!i.eventPending;
  const evName = i.eventName || '重要イベント';
  const overextended = (i.priorRunupPct ?? 0) >= 15;
  const adverse = (sdRank === 'D' || sdRank === 'E' ? 1 : 0)
    + (flow === 'panic_selling' || flow === 'distribution' ? 1 : 0)
    + (i.positionRiskLevel === 'high' || i.positionRiskLevel === 'critical' ? 1 : 0);
  const supportive = (['S', 'A', 'B'].includes(sdRank) && !squeeze && !heavy ? 1 : 0)
    + (flow === 'institutional_accumulation' ? 1 : 0);
  const hasSd = !!sdRank && sdRank !== 'Unknown';
  const hasFlow = !!flow && flow !== 'unknown';
  const eq = hasSd && hasFlow && !(i.missing ?? []).length ? 'strong'
    : hasSd || hasFlow ? 'medium'
      : i.changePct != null ? 'weak' : 'insufficient';

  const cases: ScenarioCase[] = [];

  // base
  cases.push({
    label: 'base', titleJa: `ベース：${disp}`,
    narrativeJa: improvingHeavy
      ? '需給は改善方向ですが、信用買い残の水準はまだ重いです。上値吸収を確認するまでA扱いしません。追うより押し目確認です。'
      : event
        ? `${evName}前のため、積極判断は発表後の反応を確認してからです。`
        : adverse >= 2
          ? '需給・フローの悪化が重なっており、戻りは売られやすい前提で確認を優先します。'
          : supportive >= 1 && !overextended
            ? '土台は悪くありませんが、決め打ちせず出来高を伴う継続を確認します。'
            : '強い偏りは確認できず、材料と需給の更新を待つ局面です。',
    band: eq === 'strong' || eq === 'medium' ? 'medium' : 'unknown',
    bandJa: BAND_JA[eq === 'strong' || eq === 'medium' ? 'medium' : 'unknown'],
    conditionsJa: ['大きな新規材料が出ない', '需給・フローが現状維持'],
    actionJa: improvingHeavy ? '買うなら押し目限定' : event ? 'イベント待ち' : '監視継続',
  });

  // bullish
  const bullBand: Band = supportive >= 1 && !event && !overextended && adverse === 0 && eq === 'strong'
    ? 'medium' : 'low';
  cases.push({
    label: 'bullish', titleJa: `強気：${disp}`,
    narrativeJa: squeeze
      ? '売り長のため踏み上げが続く可能性。ただし買い戻し主導なら一巡後に失速しやすく、新規大口買いとは未確定です。'
      : improvingHeavy
        ? '買い残の消化が進み、上昇日に出来高を伴って高値圏で引けられれば評価引き上げ余地(現時点では条件付き)。'
        : '需給・フローの支えが続き、出来高を伴って上値を消化できれば続伸が成立します(成立条件付き)。',
    band: bullBand, bandJa: BAND_JA[bullBand],
    conditionsJa: ['出来高を伴う上値更新', '需給悪化が出ない', ...(event ? ['イベント通過'] : [])],
    actionJa: squeeze || overextended ? '追いかけ買い注意' : '買うなら押し目限定',
  });

  // bearish
  const bearBand: Band = adverse >= 1 || heavy || (i.regimeRiskOff && i.isHeld) ? 'medium' : 'low';
  cases.push({
    label: 'bearish', titleJa: `弱気：${disp}`,
    narrativeJa: heavy || sdRank === 'D' || sdRank === 'E'
      ? '需給が重く(買い残過多)、戻り局面で売りに押されやすいシナリオです。'
      : flow === 'panic_selling' || flow === 'distribution'
        ? '売り圧力が続けば、戻りが売られる展開を想定します。'
        : '地合い悪化や外部材料次第で下押しするシナリオです(現時点では条件付き)。',
    band: bearBand, bandJa: BAND_JA[bearBand],
    conditionsJa: ['戻りが出来高薄で売られる', '需給D/Eへの悪化'],
    actionJa: i.isHeld ? 'ポジション点検' : '様子見',
  });

  if (squeeze) {
    cases.push({
      label: 'squeeze_then_fade', titleJa: `踏み上げ→失速：${disp}`,
      narrativeJa: '買い戻しで短期急伸した後、買い戻し一巡とともに失速するパターン。上昇の主体が実需買いに入れ替わるかが分岐点です。',
      band: eq === 'insufficient' ? 'unknown' : 'medium',
      bandJa: BAND_JA[eq === 'insufficient' ? 'unknown' : 'medium'],
      conditionsJa: ['買い戻し一巡', '実需買いの不在'], actionJa: '追いかけ買い注意',
    });
  }
  if (event) {
    cases.push({
      label: 'wait_event', titleJa: `イベント待ち：${evName}`,
      narrativeJa: `${evName}の結果と初動(金利・為替・指数)が方向を決めます。発表前の仕込みは結果次第で無効化されます。`,
      band: 'high', bandJa: BAND_JA.high,
      conditionsJa: [`${evName}の結果待ち`], actionJa: 'イベント待ち',
    });
  }

  // dominant ladder (Python parity)
  let dominant: Dominant;
  if (event) dominant = 'wait_event';
  else if (adverse >= 2 || (heavy && (flow === 'panic_selling' || flow === 'distribution'))) dominant = 'bearish';
  else if (bullBand === 'medium' && supportive >= 2) dominant = 'bullish';
  else if (adverse >= 1 && supportive >= 1) dominant = 'mixed';
  else if (eq === 'insufficient') dominant = 'unknown';
  else dominant = 'base';

  const heldNote = i.isHeld ? '保有中のため、同じ変化でも監視銘柄より優先度が高いです。' : '';
  const summaryJa = ({
    wait_event: `${evName}前のため判断保留が支配的です。${heldNote}`,
    bearish: `現時点では弱気シナリオ優勢 — 戻り売り前提で確認を優先。${heldNote}`,
    bullish: `強気シナリオ優勢(ただし成立条件付き)。追いかけず条件の成立を確認。${heldNote}`,
    mixed: `強弱が拮抗 — 決め打ちせず分岐条件(出来高・需給更新)を確認。${heldNote}`,
    unknown: '証拠不足のためシナリオは判定保留です。',
    base: `現時点ではベースシナリオ優勢 — 材料と需給の更新を待って判断。${heldNote}`,
  } as Record<Dominant, string>)[dominant];

  const nextChecksJa = [
    ...(event ? [`${evName}の結果と初動反応`] : []),
    ...(heavy || improvingHeavy ? ['上昇日に出来高を伴って高値圏で引けるか(上値吸収)'] : []),
    ...(squeeze ? ['買い戻し一巡後に失速しないか'] : []),
    ...(adverse ? ['戻り局面で売りが出るか'] : []),
    hasSd ? '需給(週次信用残/日次貸借残)の次回更新' : '需給データの取得',
  ].slice(0, 4);
  const invalidationJa = [
    '強気: 出来高を伴わない上昇/押し目割れで無効',
    '弱気: 出来高を伴う上値更新と需給改善(水準まで軽く)で無効',
    ...(event ? [`全体: ${evName}の結果が想定と逆なら組み直し`] : []),
  ];
  const whatWouldChangeJa = [
    '実測フローで大口買いが確認されれば強気側へ',
    ...(heavy || improvingHeavy ? ['信用買い残の水準が普通まで軽くなれば評価引き上げ'] : []),
    '需給D/Eへの悪化・フロー悪化継続なら弱気側へ',
  ].slice(0, 3);

  return {
    symbol: i.symbol.toUpperCase(), assetName: i.assetName, isHeld: i.isHeld,
    dominant, dominantJa: DOM_JA[dominant], summaryJa, cases,
    nextChecksJa, invalidationJa, whatWouldChangeJa, evidenceQuality: eq,
  };
}

/** Market Context — 地合いのシナリオ一文(端末内・帯のみ)。 */
export function marketScenarioLineJa(regimeLabel: string | null | undefined,
  eventNames: string[]): { dominant: Dominant; lineJa: string } {
  const ev = eventNames.filter(Boolean).slice(0, 2).join('/');
  if (ev) return { dominant: 'wait_event', lineJa: `${ev}待ち — 発表後の金利・為替反応が方向を決めます。イベント前の追いかけ買いは抑制。` };
  if (regimeLabel === 'EVENT_WAIT') return { dominant: 'wait_event', lineJa: '重要イベント待ちの地合い — 結果と初動反応を確認するまで方向の決め打ちはしない。' };
  if (regimeLabel === 'RISK_OFF') return { dominant: 'bearish', lineJa: 'リスク回避寄りの地合い — 高ベータの戻りは売られやすい前提で。' };
  if (regimeLabel === 'RISK_ON') return { dominant: 'base', lineJa: 'リスクオン寄りの地合い。ただし過熱銘柄の追いかけ買いは別問題(需給を確認)。' };
  return { dominant: 'base', lineJa: '地合いは中立圏 — 個別の需給・材料が優先されます。' };
}

/** Core Portfolio — 保有全体のシナリオ(端末内合成・送信なし)。 */
export function buildPortfolioScenario(heldSets: LocalScenarioSet[]):
{ dominant: Dominant; summaryJa: string; detailJa: string } | null {
  if (!heldSets.length) return null;
  const n = (d: Dominant) => heldSets.filter((s) => s.dominant === d).length;
  const bear = n('bearish'), wait = n('wait_event'), bull = n('bullish'), mixed = n('mixed');
  let dominant: Dominant; let summaryJa: string;
  if (bear >= 2 || bear >= Math.ceil(heldSets.length / 2)) {
    dominant = 'bearish';
    summaryJa = `保有${heldSets.length}銘柄中${bear}銘柄が弱気優勢 — 攻めより点検の局面です。`;
  } else if (wait >= 1) {
    dominant = 'wait_event';
    summaryJa = `保有銘柄にイベント待ちが${wait}件 — 結果確認までポートフォリオ全体で新規判断は抑制。`;
  } else if (bear >= 1 || mixed >= 2) {
    dominant = 'mixed';
    summaryJa = `保有銘柄の強弱が拮抗しています(弱気${bear}/拮抗${mixed}) — 銘柄別の分岐条件を確認。`;
  } else if (bull >= 1) {
    dominant = 'bullish';
    summaryJa = `保有銘柄に強気優勢が${bull}件。ただし成立条件付きで、追いかけ買いは別問題です。`;
  } else {
    dominant = 'base';
    summaryJa = '保有銘柄はベースシナリオ中心 — 材料と需給の更新待ちです。';
  }
  const rows = heldSets.slice(0, 5)
    .map((s) => `${jpDisplay(s.symbol, s.assetName)}=${s.dominantJa}`);
  return { dominant, summaryJa, detailJa: rows.join(' / ') };
}

/** Pro Handoff / AI Review — device-local held-aware scenario lines. */
export function scHandoffTextJa(sets: LocalScenarioSet[]): string {
  if (!sets.length) return '';
  const order: Dominant[] = ['bearish', 'wait_event', 'mixed', 'bullish', 'base', 'unknown'];
  const sorted = [...sets].sort((a, b) =>
    (a.isHeld === b.isHeld ? 0 : a.isHeld ? -1 : 1)
    || order.indexOf(a.dominant) - order.indexOf(b.dominant));
  const L = ['## Scenario Set (device-local, held-aware, 条件付き分岐)'];
  for (const s of sorted.slice(0, 6)) {
    L.push(`- [${s.dominantJa}${s.isHeld ? '・保有' : ''}] ${jpDisplay(s.symbol, s.assetName)} — ${s.summaryJa.slice(0, 70)}`);
  }
  L.push('最強の反対シナリオ: 支配シナリオの根拠(需給/フロー)は公表遅延データであり、実測フローの転換一つで入れ替わる。invalidation条件を必ず併読。');
  L.push(`注意: ${COMPLIANCE_JA}`);
  return L.join('\n');
}
