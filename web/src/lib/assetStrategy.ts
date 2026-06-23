// Rule-based per-asset strategy + short-horizon scenario probabilities, derived
// in the frontend from existing live data (action-labels + watchlist quotes +
// catalysts). NO OpenAI/Gemini call. Scenarios are decision-support, NOT
// prediction — probabilities are coarse integers that sum to 100.

import type { AssetItem } from '../types/assetItem';
import type { ActionLabel } from '../types/actionLabels';
import type { CatalystItem } from '../types/catalysts';

export interface ScenarioProb {
  label: string;
  labelJa: string;
  probability: number;
  rationaleJa: string;
}

export interface AssetStrategy {
  action: string;
  risk: 'low' | 'medium' | 'high' | '—';
  confidence: number | null;
  price?: number;
  changePct?: number;
  volume?: number;
  date?: string | null;
  strategyJa: string;
  reasonJa: string;
  nextConditionJa: string;
  whatChangesJa: string;
  scenarios: ScenarioProb[];
  scenarioHorizonJa: string;
  scenarioDisclaimerJa: string;
  catalystNoteJa: string;
  /** 大口純流入率 (-1..+1, moomoo bridge) — null/undefined when unavailable. */
  bigFlowRatio?: number | null;
  dataLimitations: string[];
  lastUpdated: number;
  status: 'live' | 'partial' | 'mock' | 'manual';
}

export interface QuoteLite {
  price: number;
  changePct: number;
  volume: number;
  date: string | null;
  status: string;
  flow?: { bigNetRatio: number } | null;
}

const SCEN_JA: Record<string, string> = {
  downside_continuation: '下値継続',
  sideways_stabilization: '横ばい / 底固め',
  rebound_attempt: '反発試行',
};

function scen(d: number, s: number, r: number, note: string): { scenarios: ScenarioProb[]; disclaimer: string } {
  return {
    scenarios: [
      { label: 'downside_continuation', labelJa: SCEN_JA.downside_continuation, probability: d, rationaleJa: note },
      { label: 'sideways_stabilization', labelJa: SCEN_JA.sideways_stabilization, probability: s, rationaleJa: '材料消化と需給次第で横ばい・底固めの可能性。' },
      { label: 'rebound_attempt', labelJa: SCEN_JA.rebound_attempt, probability: r, rationaleJa: '売られすぎの反発や買い戻しの可能性。' },
    ],
    disclaimer: 'これは予測ではなく、現在のデータに基づく短期シナリオ整理です。',
  };
}

function scenariosFor(changePct: number | undefined): { scenarios: ScenarioProb[]; disclaimer: string } {
  if (changePct == null) {
    return {
      scenarios: [
        { label: 'downside_continuation', labelJa: SCEN_JA.downside_continuation, probability: 33, rationaleJa: 'ライブ価格が未取得のため判断材料が不十分。' },
        { label: 'sideways_stabilization', labelJa: SCEN_JA.sideways_stabilization, probability: 34, rationaleJa: 'データ不十分のため広めの配分。' },
        { label: 'rebound_attempt', labelJa: SCEN_JA.rebound_attempt, probability: 33, rationaleJa: 'データ不十分のため広めの配分。' },
      ],
      disclaimer: 'データが不十分なため、広めのシナリオ配分です。予測ではありません。',
    };
  }
  if (changePct <= -7) return scen(45, 40, 15, '大幅下落でモメンタムが強く、下値継続の警戒。');
  if (changePct <= -3) return scen(40, 40, 20, 'やや大きめの下落で下値リスクが残る。');
  if (changePct < 2) return scen(30, 50, 20, '値動きは限定的で横ばい寄り。');
  if (changePct < 5) return scen(25, 50, 25, '緩やかな上昇でトレンド継続の可能性。');
  return scen(30, 45, 25, '大きく上昇した直後で過熱・押し目リスク。');
}

const ACTION_STRATEGY_JA: Record<string, string> = {
  WAIT: '様子見(新規の追いかけを抑制)',
  HOLD: '保有継続(新規は控えめ)',
  'WAIT FOR PULLBACK': '押し目待ち(追いかけ買いは回避)',
  'BUY DIP': '下落時の買い候補として監視',
  ADD: '段階的な追加を検討',
  TRIM: '一部利確 / ポジション縮小を検討',
  EXIT: '撤退を検討',
  CONTINUE: '積立を継続(長期コア)',
  'GRADUAL ADD': '段階的に追加(長期コア)',
  'DEFER LUMP SUM': '一括投入は見送り(積立は継続)',
  'NO SELL ACTION': '売却不要(長期保有)',
};

const RULE_ACTION_KEY: Record<string, string> = {
  HOLD: 'HOLD', WAIT: 'WAIT', WAIT_FOR_PULLBACK: 'WAIT FOR PULLBACK',
  BUY_DIP: 'BUY DIP', ADD: 'ADD', TRIM: 'TRIM', EXIT: 'EXIT',
};

export function deriveStrategy(
  asset: AssetItem,
  label: ActionLabel | undefined,
  quote: QuoteLite | undefined,
  catalyst: CatalystItem | undefined,
  nowTs: number,
): AssetStrategy {
  const isCore = asset.market === 'CORE' || asset.assetType === 'core_fund' || asset.assetType === 'manual_fund';
  // Crypto WITH a live CoinGecko quote flows through the normal path below;
  // only quote-less crypto (no coingecko id / fetch failed) stays manual.
  const isCryptoManual = asset.market === 'CRYPTO' && !quote;

  // Core / manual funds: calm core label, no live short-term scenarios. When a
  // NAV quote is supplied (投信総合ライブラリー基準価額, v10.111) show it.
  if (isCore) {
    const hasNav = typeof quote?.price === 'number';
    return {
      action: 'CONTINUE', risk: '—', confidence: null,
      price: hasNav ? quote!.price : undefined,
      changePct: hasNav ? quote!.changePct : undefined,
      date: quote?.date ?? null,
      strategyJa: ACTION_STRATEGY_JA.CONTINUE,
      reasonJa: hasNav
        ? '長期コア資産。基準価額(NAV)を日次でフォロー。短期の値動きで売買せず、積立方針を維持する。'
        : '長期コア資産は短期の値動きで売買せず、積立方針を維持する。',
      nextConditionJa: '積立額・目標配分の見直しが必要かを定期的に確認する。',
      whatChangesJa: 'ライフプランや配分目標の変更があれば見直す。',
      scenarios: [], scenarioHorizonJa: '長期(短期シナリオ対象外)',
      scenarioDisclaimerJa: '長期コアは短期シナリオの対象外です。',
      catalystNoteJa: '',
      dataLimitations: hasNav
        ? ['基準価額は投信総合ライブラリー(前営業日基準・日次)。約定は当日基準価額のため約定価格とは差が出ます。']
        : ['非上場投信のライブ基準価額は未取得(手動管理)。'],
      lastUpdated: nowTs, status: hasNav ? 'live' : 'manual',
    };
  }

  // Crypto whose live quote is unavailable (no coingecko id, or the fetch
  // failed this session): honest manual placeholder, no fake price.
  if (isCryptoManual) {
    const sc = scenariosFor(undefined);
    return {
      action: 'WAIT', risk: '—', confidence: null,
      strategyJa: '監視のみ(ライブ価格の取得待ち)',
      reasonJa: 'CoinGeckoのライブ価格を取得できていません(接続待ち/一時的な失敗)。',
      nextConditionJa: 'ライブ価格の取得後に価格とシナリオを表示。',
      whatChangesJa: 'ライブ価格が取得できれば再評価。',
      scenarios: sc.scenarios, scenarioHorizonJa: '1〜3営業日', scenarioDisclaimerJa: sc.disclaimer,
      catalystNoteJa: '', dataLimitations: ['暗号資産のライブ価格が未取得(CoinGecko接続待ち)。'],
      lastUpdated: nowTs, status: 'manual',
    };
  }

  const changePct = quote?.changePct;
  const flowRatio = label?.supportingData?.bigFlowRatio ?? quote?.flow?.bigNetRatio ?? null;
  const sc = scenariosFor(changePct);
  const action = label ? (RULE_ACTION_KEY[label.action] ?? label.action) : (quote ? 'HOLD' : 'WAIT');
  const risk = (label?.risk ?? (quote ? 'medium' : '—')) as AssetStrategy['risk'];
  const confidence = label ? label.confidence : null;

  let catalystNote = '';
  const dataLimitations: string[] = [
    flowRatio != null
      ? 'VWAP・板情報は未取得(大口フローはmoomooブリッジから取得)。'
      : 'VWAP・資金フロー・板情報は未取得。',
    '行動ラベルはルールベース(GPT/Geminiは未使用)。',
  ];
  if (asset.market === 'CRYPTO') {
    dataLimitations.push('暗号資産は行動ラベルエンジン未対応(価格は24h変化基準、CoinGecko)。');
  }
  if (catalyst) {
    const bits: string[] = [];
    if (catalyst.earnings?.date) bits.push(`決算 ${catalyst.earnings.date}(D-${catalyst.earnings.daysUntil})`);
    if (catalyst.filings?.length) bits.push(`直近開示 ${catalyst.filings[0].form} ${catalyst.filings[0].filingDate}`);
    if (catalyst.news?.length) bits.push(`ニュース ${catalyst.news.length}件(7日)`);
    catalystNote = `${catalyst.catalystRisk.toUpperCase()} — ${bits.join(' / ') || '目立つ材料なし'}`;
  } else {
    dataLimitations.push('銘柄固有の材料(決算/開示/ニュース)は未取得。');
  }

  const status: AssetStrategy['status'] =
    !quote ? 'mock' : (quote.status === 'live' ? (label ? 'live' : 'partial') : 'mock');

  return {
    action, risk, confidence,
    price: quote?.price, changePct: quote?.changePct, volume: quote?.volume, date: quote?.date,
    bigFlowRatio: flowRatio,
    strategyJa: ACTION_STRATEGY_JA[action] ?? '判断整理中',
    reasonJa: label?.reasonJa ?? (quote ? '相場全体の地合いに沿って判断。' : 'ライブ価格が未取得のため中立。'),
    nextConditionJa: label?.nextConditionJa ?? '次の値動きとイベント日程を確認する。',
    whatChangesJa: catalyst?.actionImpact === 'wait_for_event'
      ? 'イベント通過後の反応で判断が変わりうる。'
      : '下げ止まり/出来高/地合いの変化で判断が変わりうる。',
    scenarios: sc.scenarios, scenarioHorizonJa: '1〜3営業日', scenarioDisclaimerJa: sc.disclaimer,
    catalystNoteJa: catalystNote, dataLimitations,
    lastUpdated: nowTs, status,
  };
}
