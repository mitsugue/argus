import { coingeckoIdOf } from '../../lib/cryptoIds';
import React, { useMemo, useState } from 'react';
import {
  DndContext, closestCenter, PointerSensor, KeyboardSensor, useSensor, useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, arrayMove, useSortable,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { useDownsideIncidents, type DownsideIncident } from '../../hooks/useDownsideIncidents';
import { useFundNav } from '../../hooks/useFundNav';
import { resolveSignal, OVERRIDE_LABEL_JA, type OwnerState } from '../../domain/actionLevel';
import { holderPosture } from '../../lib/holderPosture';
import { SignedValue } from '../common/SignedValue';
import { getNumericTone, TONE_VAR } from '../../lib/numericTone';
import { useLocale, t, pick, getLocale } from '../../i18n';
import { useJapanWatchlist } from '../../hooks/useJapanWatchlist';
import { useUSWatchlist } from '../../hooks/useUSWatchlist';
import { useCryptoWatchlist } from '../../hooks/useCryptoWatchlist';
import { useActionLabels } from '../../hooks/useActionLabels';
import { useCatalysts } from '../../hooks/useCatalysts';
import { useRatesSnapshot } from '../../hooks/useRatesSnapshot';
import { useAIJudgment } from '../../hooks/useAIJudgment';
import { deriveStrategy, bestAssetName, type AssetStrategy, type QuoteLite } from '../../lib/assetStrategy';
import { buildExposure, valueHolding, fmtMoney, fmtSigned, currencyOf, type ExposureSummary } from '../../lib/portfolio';
import { simulateAdd } from '../../lib/whatif';
import { getNote, saveNote } from '../../lib/researchNotes';
import { GENRES, genreOf, type AssetItem } from '../../types/assetItem';
import type { ActionLabel } from '../../types/actionLabels';
import type { AIJudgmentLabel } from '../../types/aiJudgment';
import type { CatalystItem } from '../../types/catalysts';

interface Props {
  assets: AssetItem[];
  onReorder: (orderedIds: string[]) => void;
  expandedId: string | null;
  onToggleExpand: (id: string) => void;
  onRemove: (id: string) => void;
  onUpdateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
}

const ACTION_COLOR: Record<string, string> = {
  EXIT: 'var(--red)', TRIM: 'var(--red)', 'WAIT FOR PULLBACK': 'var(--amber)',
  WAIT: 'var(--blue)', 'BUY DIP': 'var(--green)', ADD: 'var(--green)', HOLD: 'var(--text-sub)',
  CONTINUE: 'var(--green)', 'GRADUAL ADD': 'var(--green)', 'DEFER LUMP SUM': 'var(--amber)', 'NO SELL ACTION': 'var(--text-sub)',
};
const STATUS_COLOR: Record<string, string> = {
  live: 'var(--green)', partial: 'var(--amber)', mock: 'var(--amber)', manual: 'var(--text-muted)',
};

function fmtPrice(market: string, v?: number): string {
  if (v == null) return '—';
  if (market === 'JP' || market === 'CORE' || market === 'FUND') return `¥${Math.round(v).toLocaleString('en-US')}`;
  if (market === 'US') return `$${v.toFixed(2)}`;
  if (market === 'CRYPTO') {
    return v >= 1000 ? `$${Math.round(v).toLocaleString('en-US')}` : `$${v.toFixed(2)}`;
  }
  return String(v);
}
function fmtPct(p?: number): string {
  if (p == null) return '';
  const s = p > 0 ? '+' : p < 0 ? '−' : '';
  return `${s}${Math.abs(p).toFixed(2)}%`;
}
function pctClass(p?: number): string {
  if (p == null) return 'asset-row__chg';
  if (p > 0.05) return 'asset-row__chg asset-row__chg--up';
  if (p < -0.05) return 'asset-row__chg asset-row__chg--down';
  return 'asset-row__chg';
}
function ageMin(ts: number): string {
  const m = Math.max(0, Math.round((Date.now() - ts) / 60000));
  return m < 1 ? 'just now' : `${m}m ago`;
}

// ── Data-freshness honesty ──
// J-Quants free plan lags ~12 weeks: a quote can be "live" (really fetched)
// yet months old. Surface that as an amber "delayed Xw" instead of a green
// "live" — an investment app must never dress stale data as fresh.
function lagDays(date?: string | null): number | null {
  if (!date) return null;
  const t = Date.parse(`${date}T00:00:00+09:00`);
  if (!Number.isFinite(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86_400_000));
}

function freshnessOf(strat: AssetStrategy): { text: string; color: string } {
  if (strat.status === 'manual') return { text: 'manual', color: STATUS_COLOR.manual };
  if (strat.status === 'mock')   return { text: 'mock',   color: STATUS_COLOR.mock };
  const lag = lagDays(strat.date);
  if (lag != null && lag > 7) {
    const text = lag >= 14 ? `delayed ${Math.round(lag / 7)}w` : `delayed ${lag}d`;
    return { text, color: 'var(--amber)' };
  }
  return { text: strat.status, color: STATUS_COLOR[strat.status] ?? 'var(--text-muted)' };
}

const GENRE_COLOR: Record<string, string> = {
  jp: 'var(--blue)', us: 'var(--green)', funds: 'var(--amber)', crypto: 'var(--cyan)',
};

// Compact portfolio header: per-currency totals + unrealized P/L + JPY-combined
// allocation. All math is client-side (lib/portfolio.ts); holdings never leave
// the device. Shown only once at least one holding is entered.
const ExposureCard: React.FC<{
  assets: AssetItem[];
  exp: ExposureSummary;
}> = ({ assets, exp }) => {
  const anyHolding = assets.some((a) => (a.quantity ?? 0) > 0 && a.avgCost != null);
  if (!anyHolding) {
    return (
      <div className="card exp exp--hint">
        <span className="exp__title">Portfolio Exposure</span>
        <p className="exp__hint">銘柄の行を開いて「保有数量・平均取得単価」を入力すると、ここに評価額・含み損益・配分が表示されます(データはこの端末内のみ)。</p>
      </div>
    );
  }
  const plColor = (v: number) => (v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-sub)');
  return (
    <div className="card exp">
      <div className="exp__head">
        <span className="exp__title">Portfolio Exposure</span>
        <span className="exp__note">端末内のみ・未実現損益</span>
      </div>
      <div className="exp__totals">
        {(['JPY', 'USD'] as const).filter((c) => exp.totals[c].value > 0).map((c) => (
          <span key={c} className="exp__total">
            <b>{fmtMoney(c, exp.totals[c].value)}</b>
            <span style={{ color: plColor(exp.totals[c].pl) }}>
              {' '}{fmtSigned(c, exp.totals[c].pl)}
              （{exp.totals[c].cost > 0 ? `${exp.totals[c].pl >= 0 ? '+' : ''}${((exp.totals[c].pl / exp.totals[c].cost) * 100).toFixed(1)}%` : '—'}）
            </span>
          </span>
        ))}
        {exp.combinedJpy != null && exp.totals.USD.value > 0 && exp.totals.JPY.value > 0 && (
          <span className="exp__combined">
            合計 ≈ {fmtMoney('JPY', exp.combinedJpy)}
            <span style={{ color: plColor(exp.combinedPlJpy ?? 0) }}>{' '}{fmtSigned('JPY', exp.combinedPlJpy ?? 0)}</span>
            {exp.usdJpy != null && <span className="exp__fx">（USD/JPY {exp.usdJpy}）</span>}
          </span>
        )}
      </div>
      {exp.byGenre.length > 0 && (
        <>
          <div className="exp__bar" aria-hidden>
            {exp.byGenre.map((g) => (
              <span key={g.key} style={{ width: `${g.pct}%`, background: GENRE_COLOR[g.key] }} />
            ))}
          </div>
          <div className="exp__legend">
            {exp.byGenre.map((g) => (
              <span key={g.key}>
                <span className="exp__dot" style={{ background: GENRE_COLOR[g.key] }} />
                {g.title} {g.pct.toFixed(1)}%
              </span>
            ))}
          </div>
        </>
      )}
      {exp.unpriced.length > 0 && (
        <p className="exp__unpriced">ライブ価格未取得のため対象外: {exp.unpriced.join(', ')}（投信の基準価額は未対応）</p>
      )}
    </div>
  );
};

// What-if simulator (v10.1): "¥X を銘柄Y に追加したら配分とシナリオ別損益は
// どう動くか" — SCENARIO ANALYSIS over assumed bands, never a forecast.
// Client-side only; uses the same live quotes + rule scenarios as the cards.
const WhatIfPanel: React.FC<{
  assets: AssetItem[];
  quotes: Map<string, QuoteLite>;
  labels: Map<string, ActionLabel>;
  cats: Map<string, CatalystItem>;
  exp: ExposureSummary;
  usdJpy: number | null;
  mountTs: number;
}> = ({ assets, quotes, labels, cats, exp, usdJpy, mountTs }) => {
  const [open, setOpen] = useState(false);
  const [sel, setSel] = useState('');
  const [amt, setAmt] = useState('');

  const candidates = useMemo(
    () => assets.filter((a) => {
      const q = quotes.get(a.symbol);
      return q && q.status === 'live';
    }),
    [assets, quotes],
  );
  const selAsset = candidates.find((a) => a.symbol === sel) ?? null;
  const ccy = selAsset ? currencyOf(selAsset.market) : 'JPY';

  const result = useMemo(() => {
    const amount = Number(amt);
    if (!selAsset || !(amount > 0)) return null;
    const q = quotes.get(selAsset.symbol)!;
    const strat = deriveStrategy(selAsset, labels.get(selAsset.symbol), q, cats.get(selAsset.symbol), mountTs);
    return simulateAdd({
      symbol: selAsset.symbol, currency: currencyOf(selAsset.market),
      price: q.price, amount, scenarios: strat.scenarios,
      exposure: exp, usdJpy,
    });
  }, [selAsset, amt, quotes, labels, cats, exp, usdJpy, mountTs]);

  if (candidates.length === 0) return null;
  return (
    <div className="card whatif">
      <button className="whatif__toggle" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="whatif__caret">{open ? '▾' : '▸'}</span>
        What-if シミュレーション
        <span className="whatif__sub">追加投資の配分・シナリオ別損益(予測ではなくシナリオ整理)</span>
      </button>
      {open && (
        <div className="whatif__body">
          <div className="whatif__form">
            <label>銘柄
              <select value={sel} onChange={(e) => setSel(e.target.value)}>
                <option value="">選択…</option>
                {candidates.map((a) => (
                  <option key={a.id} value={a.symbol}>
                    {a.symbol} {bestAssetName(a, quotes.get(a.symbol)?.name)}
                  </option>
                ))}
              </select>
            </label>
            <label>追加投資額({ccy === 'JPY' ? '¥' : '$'})
              <input type="number" inputMode="decimal" min="0" step="any" value={amt}
                     placeholder={ccy === 'JPY' ? '300000' : '2000'}
                     onChange={(e) => setAmt(e.target.value)} />
            </label>
          </div>
          {result && (
            <div className="whatif__result">
              <p className="whatif__line">
                追加: <b>{result.addQuantity.toFixed(result.addQuantity >= 10 ? 0 : 4)}</b> 単位 @ {fmtMoney(result.currency, result.price)}
                （投資額 {fmtMoney(result.currency, result.amount)}）
              </p>
              {result.assetShareAfterPct != null && (
                <p className="whatif__line">
                  配分: {sel} が {result.assetShareBeforePct?.toFixed(1) ?? '0.0'}% → <b>{result.assetShareAfterPct.toFixed(1)}%</b>
                  {result.portfolioAfterJpy != null && <>（追加後ポートフォリオ ≈ {fmtMoney('JPY', result.portfolioAfterJpy)}）</>}
                </p>
              )}
              {result.warnings.map((w, i) => (
                <p className="whatif__warn" key={i}>⚠ {w}</p>
              ))}
              <div className="whatif__bands">
                <span className="whatif__bands-head">シナリオ別損益帯(1〜3営業日・仮定幅)</span>
                {result.bands.map((b) => (
                  <div className="whatif__band" key={b.label}>
                    <span className="whatif__band-label">{b.labelJa}</span>
                    <span className="whatif__band-prob">{b.probability}%</span>
                    <span className="whatif__band-range">
                      {fmtSigned(result.currency, b.plLow)} 〜 {fmtSigned(result.currency, b.plHigh)}
                    </span>
                  </div>
                ))}
                <p className="whatif__expected">
                  確率加重の中央値(参考): <b style={{ color: TONE_VAR[getNumericTone(result.expectedMid)] }}>
                    {fmtSigned(result.currency, result.expectedMid)}
                  </b>
                </p>
              </div>
              <p className="whatif__disc">
                仮定幅(下値継続 −10〜−4% / 横ばい ±2% / 反発 +3〜+8%)にルールエンジンのシナリオ確率を掛けた整理です。
                予測・推奨ではありません。
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

const AI_VIEW_JA: Record<string, string> = {
  confirm: '同意', caution: '注意', disagree: '不同意', unavailable: '—',
};
const AI_VIEW_COLOR: Record<string, string> = {
  confirm: 'var(--green)', caution: 'var(--amber)', disagree: 'var(--red)', unavailable: 'var(--text-muted)',
};

const SortableAssetRow: React.FC<{
  asset: AssetItem; strat: AssetStrategy; expanded: boolean;
  liveName?: string | null;
  onToggleExpand: (id: string) => void; onRemove: (id: string) => void;
  onUpdateHolding: Props['onUpdateHolding'];
  aiLabel?: AIJudgmentLabel;
  aiAgeMin?: number | null;
  incident?: DownsideIncident;
}> = ({ asset, strat, expanded, liveName, onToggleExpand, onRemove, onUpdateHolding, aiLabel, aiAgeMin, incident }) => {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: asset.id });
  // Entry Scout (v10.15, user request 2026-06-13): on-demand 瞬間診断 for the
  // buy-entry moment — trend/overheat from 60d history + big-money flow +
  // event/posture context, with honest data-gap disclosure. JP only (Phase 1).
  interface ScoutData {
    status: string;
    lastClose?: number; lastDate?: string;
    metrics?: { rsi14: number; ma25DiffPct: number | null; ret5: number | null; ret20: number | null; consecDown: number; volRatio5v20: number | null };
    flow?: { bigNetRatio: number | null; ageMin: number | null };
    nisshokin?: { ratio: number | null; loan: number; short: number } | null;
    shortDisclosed?: { ratioPct: number; reporters: number } | null;
    flowInference?: {
      classification: string;
      probabilities: { newLongAccumulation: number; shortCovering: number; distribution: number; retailNoise: number; unconfirmed: number };
      confidence: string; reasonsJa: string[]; nextConditionJa: string;
    };
    assessment?: { stance: string; score: number; reasonsJa: string[] };
    catalystContext?: { items: { kind: string; level?: string; labelJa?: string; count?: number; headline?: string | null; noteJa?: string }[]; noteJa: string };
    scoreTrackRecord?: { n: number; upRate: number | null; avgRetPct: number | null } | null;
    // v3 (v10.30): one-line call + moat-grounded story + calibration the LLM lacks.
    callJa?: string; narrativeJa?: string;
    engineCalibration?: { n: number; hitRate: number | null; days?: number } | null;
    postureCalibration?: { posture: string; n: number; hitRate: number | null } | null;
    dataGapsJa?: string[]; noteJa?: string;
  }
  const FLOW_LABEL: Record<string, string> = {
    NEW_LONG_ACCUMULATION: '新規買い主導', SHORT_COVERING: '買い戻し主導(踏み上げ)',
    DISTRIBUTION: '上値での分配(売り抜け疑い)', RETAIL_NOISE: '短期ノイズ', UNCONFIRMED: '判定不能(データ不足)',
  };
  const [scout, setScout] = useState<null | 'loading' | 'error' | ScoutData>(null);
  async function runScout() {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) { setScout('error'); return; }
    setScout('loading');
    try {
      const mkt = asset.market === 'US' ? '&market=US' : '';
      const r = await fetch(`${backend.replace(/\/$/, '')}/api/argus/entry-scout?symbol=${encodeURIComponent(asset.symbol)}${mkt}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setScout((await r.json()) as ScoutData);
    } catch { setScout('error'); }
  }

  // Per-symbol Pro Handoff (v10.12.2, user request): a SMALL copy button that
  // builds a prompt about THIS symbol only — the global handoff stays for the
  // whole-market consult. Client-side from data already on the card; no API.
  // LLM相談 (v10.30, user request 「ボタンは一つでいい」+「モート起点に」):
  // ONE handoff button. The prompt LEADS with what Gemini/GPT can't fetch —
  // big-money flow, 信用需給(日証金/空売り), the flow-class read, and ARGUS's
  // OWN calibrated track record — and explicitly tells the LLM "you already
  // know the news; corroborate or refute THIS with OSINT". So the answer comes
  // back anchored to ARGUS instead of generic web sentiment.
  const [llmCopied, setLlmCopied] = useState(false);
  const [note, setNote] = useState(() => getNote(asset.symbol)?.text ?? '');
  const [noteSaved, setNoteSaved] = useState(false);
  async function copyLlmConsult() {
    const name0 = bestAssetName(asset, liveName);
    const sc = (scout && typeof scout === 'object' && scout.status === 'live') ? scout : null;
    const L: string[] = [];
    L.push(`あなたは投資の専門家です。私の判断支援アプリARGUSが出した「${asset.symbol} ${name0}」(${asset.market})の診断を渡します。`);
    L.push('大前提: ニュースや一般的な地合いはあなたの方が詳しい。だからここでは、ARGUSが掴んでいる「Web検索だけでは取れない情報」を軸に判断してほしい。');
    L.push('');
    L.push('【ARGUSにしか見えない情報 — これを最重視して】');
    const flow = sc?.flow?.bigNetRatio ?? strat.bigFlowRatio;
    if (flow != null) L.push(`■ 大口資金フロー(moomoo板・純流入率): ${(flow * 100).toFixed(0)}%`);
    if (sc?.nisshokin?.ratio != null) L.push(`■ 日証金倍率: ${sc.nisshokin.ratio}（1未満=売り長=踏み上げ燃料）`);
    if (sc?.shortDisclosed) L.push(`■ 機関の大口空売り(JPX開示): ${sc.shortDisclosed.ratioPct}%（${sc.shortDisclosed.reporters}社）`);
    if (sc?.flowInference && sc.flowInference.classification !== 'UNCONFIRMED') {
      const p = sc.flowInference.probabilities;
      L.push(`■ フロー推定(誰が動かしているか): 新規買い${Math.round(p.newLongAccumulation * 100)}% / 買い戻し${Math.round(p.shortCovering * 100)}% / 分配${Math.round(p.distribution * 100)}% / ノイズ${Math.round(p.retailNoise * 100)}%（確度${sc.flowInference.confidence}）`);
    }
    if (sc?.scoreTrackRecord && sc.scoreTrackRecord.n >= 5) {
      const t = sc.scoreTrackRecord;
      L.push(`■ ARGUS校正: このscore水準は過去${t.n}件中${t.upRate != null ? `${Math.round(t.upRate * 100)}%上昇` : ''}${t.avgRetPct != null ? `(平均${t.avgRetPct >= 0 ? '+' : ''}${t.avgRetPct}%)` : ''}`);
    }
    if (sc?.postureCalibration?.hitRate != null) L.push(`■ この地合い(${sc.postureCalibration.posture})のエンジン的中率: ${Math.round(sc.postureCalibration.hitRate * 100)}%（n=${sc.postureCalibration.n}）`);
    else if (sc?.engineCalibration?.hitRate != null) L.push(`■ ARGUSエンジン全体の的中率: ${Math.round(sc.engineCalibration.hitRate * 100)}%（n=${sc.engineCalibration.n}）`);
    if (sc?.callJa) L.push(`■ ARGUSの一言コール: ${sc.callJa}`);
    L.push('');
    L.push('【参考(あなたの方が詳しいはず)】');
    if (strat.status !== 'mock' && strat.price != null) L.push(`■ 現在値 ${strat.price}（前日比 ${strat.changePct != null ? `${strat.changePct >= 0 ? '+' : ''}${strat.changePct.toFixed(2)}%` : '—'}）・ARGUS判断 ${strat.action}`);
    if (sc?.metrics) L.push(`■ テクニカル: RSI14=${sc.metrics.rsi14}・25日線乖離${sc.metrics.ma25DiffPct ?? '—'}%`);
    if (strat.catalystNoteJa) L.push(`■ 直近の材料(ARGUS把握分): ${strat.catalystNoteJa}`);
    L.push('');
    L.push('依頼:');
    L.push('(1) Web/Deep ResearchのOSINT(直近2週の開示・決算・大株主/空売り/自社株買い・業界/国策)で、上のARGUSの需給読みを「補強 or 反証」して');
    L.push('(2) 強気材料と弱気材料を対比');
    L.push('(3) 最後に必ず:【新規買い/買い戻し/様子見/回避】の確率配分(%)・確信度(高/中/低)・根拠・出典URL・次に確認する条件。断定でなく確率で。');
    L.push('売買指示ではなく判断材料の整理として。');
    const text = L.join('\n');
    try {
      await navigator.clipboard.writeText(text);
      setLlmCopied(true);
      window.setTimeout(() => setLlmCopied(false), 2500);
    } catch {
      window.prompt('コピーできませんでした。手動で選択してください:', text);
    }
  }
  const style: React.CSSProperties = { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1 };
  const name = bestAssetName(asset, liveName);
  const fresh = freshnessOf(strat);
  const hp = holderPosture(asset, strat, incident);   // position-aware guidance (held only, v10.113)
  const HP_COLOR: Record<string, string> = { red: '#F87171', amber: '#FBBF24', green: '#34D399', neutral: 'var(--text-sub)' };
  // Action Level signal (v10.119) — never show the ambiguous raw action alone.
  const sig = resolveSignal(strat.action, {
    downsideOverride: incident?.actionOverride,
    dataQuality: strat.status === 'live' ? 'LIVE' : strat.status === 'mock' ? 'MOCK' : 'PARTIAL',
    materialDownside: !!incident,
    ownerState: (incident?.ownerState as OwnerState) || undefined,
  });
  // Mock rows never show plausible-but-fake numbers — "—" instead.
  const priceShown = strat.status === 'mock' ? undefined : strat.price;
  const chgShown   = strat.status === 'mock' ? undefined : strat.changePct;

  return (
    <div ref={setNodeRef} style={style} className={`asset-row${expanded ? ' asset-row--open' : ''}${isDragging ? ' asset-row--drag' : ''}`}>
      <div className="asset-row__head">
        <button className="asset-row__handle" aria-label={`Reorder ${asset.symbol}`} {...attributes} {...listeners}>⋮⋮</button>
        <button
          className="asset-row__main"
          aria-expanded={expanded}
          onClick={() => onToggleExpand(asset.id)}
        >
          <span className="asset-row__caret">{expanded ? '▾' : '▸'}</span>
          <span className="asset-row__id">
            <span className="asset-row__sym">{asset.symbol}</span>
            <span className="asset-row__name">{name}</span>
          </span>
          <span className="asset-row__price">{fmtPrice(asset.market, priceShown)}</span>
          <span className="asset-row__chg">{chgShown == null ? '—' : <SignedValue value={chgShown} suffix="%" arrow={false} />}</span>
          <span className="asset-row__action" style={{ color: `var(${sig.token})` }} title={`${sig.labelEn} (legacy ${strat.action})`}>
            {getLocale() === 'ja' ? sig.labelJa : sig.labelEn}{sig.permissions.newEntry === 'BLOCKED' && <span className="asset-row__sig-blk"> ⊘</span>}
          </span>
          {incident && (
            <span className="asset-row__override"
              style={{ color: ['EXIT_WATCH', 'TRIM_WATCH'].includes(incident.actionOverride) ? '#F87171' : '#FBBF24' }}>
              ⚠ {OVERRIDE_LABEL_JA[incident.actionOverride] ?? incident.actionOverride}
            </span>
          )}
          {hp && (
            <span className="asset-row__holder" style={{ color: HP_COLOR[hp.tone] }} title={t('hp.heldCall')}>
              {t('hp.held')}: {pick(hp.labelEn, hp.labelJa)}
            </span>
          )}
          <span className="asset-row__meta">
            {strat.risk !== '—' && <span>risk {strat.risk}</span>}
            {strat.confidence != null && <span>· {Math.round(strat.confidence * 100)}%</span>}
            {incident && incident.ownerState && incident.ownerState !== 'watch' && (
              <span> · {incident.ownerState}</span>
            )}
          </span>
          <span className="asset-row__status" style={{ color: fresh.color }}>{fresh.text}</span>
        </button>
      </div>

      {expanded && (
        <div className="asset-row__detail">
          {hp && (
            <div className="asset-detail__holder" style={{ borderColor: HP_COLOR[hp.tone] }}>
              <span className="asset-detail__holder-label" style={{ color: HP_COLOR[hp.tone] }}>{t('hp.heldCall')}: {pick(hp.labelEn, hp.labelJa)}</span>
              {hp.plPct != null && (
                <span className="asset-detail__holder-pl" style={{ color: hp.plPct >= 0 ? '#34D399' : '#F87171' }}>
                  {hp.plPct >= 0 ? '+' : '−'}{Math.abs(hp.plPct).toFixed(1)}%
                </span>
              )}
              <p className="asset-detail__holder-reason">{pick(hp.reasonEn, hp.reasonJa)}</p>
            </div>
          )}
          {incident && (
            <div className="asset-detail__downside">
              <div className="asset-detail__downside-head">
                WHY DOWN? <span className="asset-detail__downside-pct">{typeof incident.changePct === 'number' ? `${incident.changePct.toFixed(1)}%` : ''}</span>
                <span className="asset-detail__downside-ovr"
                  style={{ color: ['EXIT_WATCH', 'TRIM_WATCH'].includes(incident.actionOverride) ? '#F87171' : '#FBBF24' }}>
                  Rule: {incident.currentAction} → Override: {incident.actionOverride}
                </span>
              </div>
              <div className="asset-detail__downside-causes">
                {incident.causeBuckets.slice(0, 3).map((b) => (
                  <span key={b.cause} className="asset-detail__downside-cause">
                    {b.cause} {Math.round(b.probability * 100)}%
                  </span>
                ))}
              </div>
              <p className="asset-detail__downside-line">{incident.reasonJa}</p>
              <p className="asset-detail__downside-line"><b>やってはいけない:</b> {incident.doNotDoJa}</p>
              <p className="asset-detail__downside-line"><b>確認条件:</b> {incident.nextConditionJa}</p>
              {incident.missingData.length > 0 && (
                <p className="asset-detail__downside-line asset-detail__downside-missing">
                  <b>欠損データ:</b> {incident.missingData.join(' / ')}
                </p>
              )}
            </div>
          )}
          <div className="asset-detail__grid">
            <div><span className="asset-detail__k">Strategy</span><span className="asset-detail__v">{strat.strategyJa}</span></div>
            <div><span className="asset-detail__k">Why</span><span className="asset-detail__v">{strat.reasonJa}</span></div>
            <div><span className="asset-detail__k">What to wait for</span><span className="asset-detail__v">{strat.nextConditionJa}</span></div>
            <div><span className="asset-detail__k">What changes it</span><span className="asset-detail__v">{strat.whatChangesJa}</span></div>
            {strat.catalystNoteJa && <div><span className="asset-detail__k">Catalyst</span><span className="asset-detail__v">{strat.catalystNoteJa}</span></div>}
            {strat.bigFlowRatio != null && (
              <div><span className="asset-detail__k">Big-money flow</span>
                <span className="asset-detail__v" style={{ color: strat.bigFlowRatio >= 0.2 ? 'var(--green)' : strat.bigFlowRatio <= -0.2 ? 'var(--red)' : 'var(--text-sub)' }}>
                  大口純流入率 {(strat.bigFlowRatio * 100).toFixed(1)}%（本日累計・moomoo）
                </span>
              </div>
            )}
          </div>

          {/* AI second opinion (cached GPT-5.5 + Gemini run — read-only, v10.3). */}
          {aiLabel && (
            <div className="asset-ai">
              <div className="asset-ai__head">
                <span className="asset-ai__tag">AI予想{aiAgeMin != null ? `・${aiAgeMin < 60 ? `${aiAgeMin}分前` : `${Math.round(aiAgeMin / 60)}時間前`}の実行` : ''}</span>
                <span style={{ color: AI_VIEW_COLOR[aiLabel.aiView] ?? 'var(--text-sub)' }}>
                  ルール判定に{AI_VIEW_JA[aiLabel.aiView] ?? aiLabel.aiView}
                </span>
                <span className="asset-ai__action">AI提案: <b>{aiLabel.aiFinalAction}</b>（確信度{Math.round((aiLabel.confidence ?? 0) * 100)}%）</span>
              </div>
              {aiLabel.reasonJa && <p className="asset-ai__reason">{aiLabel.reasonJa}</p>}
              {aiLabel.redFlags?.length > 0 && (
                <p className="asset-ai__flags">⚑ {aiLabel.redFlags.join(' / ')}</p>
              )}
            </div>
          )}

          {/* Holdings (v10.0) — device-local; drives the Portfolio Exposure card. */}
          {(() => {
            const livePrice = (strat.status === 'live' || strat.status === 'partial') ? strat.price : undefined;
            const hv = valueHolding(asset, livePrice);
            const num = (v: string) => (v.trim() === '' ? null : Number(v));
            return (
              <div className="asset-hold">
                <span className="asset-detail__k">Holding（端末内のみ）</span>
                <div className="asset-hold__body">
                  <label className="asset-hold__field">数量
                    <input type="number" inputMode="decimal" min="0" step="any"
                      defaultValue={asset.quantity ?? ''}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={(e) => onUpdateHolding(asset.id, { quantity: num(e.currentTarget.value) })} />
                  </label>
                  <label className="asset-hold__field">平均取得単価
                    <input type="number" inputMode="decimal" min="0" step="any"
                      defaultValue={asset.avgCost ?? ''}
                      onClick={(e) => e.stopPropagation()}
                      onBlur={(e) => onUpdateHolding(asset.id, { avgCost: num(e.currentTarget.value) })} />
                  </label>
                  {hv && (
                    <span className="asset-hold__val">
                      評価 <b>{fmtMoney(hv.currency, hv.value)}</b>
                      {' ／ 損益 '}
                      <b style={{ color: TONE_VAR[getNumericTone(hv.pl)] }}>
                        {fmtSigned(hv.currency, hv.pl)}（{hv.plPct >= 0 ? '+' : ''}{hv.plPct.toFixed(1)}%）
                      </b>
                    </span>
                  )}
                </div>
              </div>
            );
          })()}
          {strat.scenarios.length > 0 && (
            <div className="asset-scen">
              <div className="asset-scen__head">Scenario probabilities · {strat.scenarioHorizonJa}</div>
              {strat.scenarios.map((s) => (
                <div className="asset-scen__row" key={s.label}>
                  <span className="asset-scen__label">{s.labelJa}</span>
                  <span className="asset-scen__bar"><span style={{ width: `${s.probability}%` }} /></span>
                  <span className="asset-scen__pct">{s.probability}%</span>
                  <span className="asset-scen__why">{s.rationaleJa}</span>
                </div>
              ))}
              <div className="asset-scen__disc">{strat.scenarioDisclaimerJa}</div>
            </div>
          )}
          {strat.dataLimitations.length > 0 && (
            <div className="asset-detail__limits">
              <span className="asset-detail__k">Data limitations</span>
              <ul>{strat.dataLimitations.map((d, i) => <li key={i}>{d}</li>)}</ul>
            </div>
          )}
          {scout === 'error' && (
            <div className="scout scout--note">⚡ 診断を取得できませんでした(時間をおいて再試行)。</div>
          )}
          {scout && scout !== 'loading' && scout !== 'error' && scout.status !== 'live' && (
            <div className="scout scout--note">⚡ {(scout as ScoutData & { noteJa?: string }).noteJa ?? '診断対象外です。'}</div>
          )}
          {scout && scout !== 'loading' && scout !== 'error' && scout.status === 'live' && scout.assessment && (
            <div className="scout">
              {scout.callJa && <div className="scout__call">⚡ {scout.callJa}</div>}
              {scout.narrativeJa && <div className="scout__story">{scout.narrativeJa}</div>}
              <div className="scout__stance">{scout.assessment.stance} <span className="scout__score">score {scout.assessment.score >= 0 ? '+' : ''}{scout.assessment.score}</span></div>
              {scout.scoreTrackRecord && scout.scoreTrackRecord.n >= 5 && (
                <div className="scout__track">
                  📊 この水準の実績: 過去{scout.scoreTrackRecord.n}件中
                  {scout.scoreTrackRecord.upRate != null && ` ${Math.round(scout.scoreTrackRecord.upRate * 100)}%が上昇`}
                  {scout.scoreTrackRecord.avgRetPct != null && `(平均${scout.scoreTrackRecord.avgRetPct >= 0 ? '+' : ''}${scout.scoreTrackRecord.avgRetPct}%)`}
                </div>
              )}
              <ul className="scout__reasons">
                {scout.assessment.reasonsJa.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
              {scout.flowInference && scout.flowInference.classification !== 'UNCONFIRMED' && (
                <div className="scout__flow">
                  <div className="scout__flow-head">
                    🐋 大口の正体: <b>{FLOW_LABEL[scout.flowInference.classification] ?? scout.flowInference.classification}</b>
                    <span className="scout__flow-conf"> (確度 {scout.flowInference.confidence})</span>
                  </div>
                  <div className="scout__flow-bars">
                    {([['新規買い', scout.flowInference.probabilities.newLongAccumulation],
                       ['買い戻し', scout.flowInference.probabilities.shortCovering],
                       ['分配', scout.flowInference.probabilities.distribution],
                       ['ノイズ', scout.flowInference.probabilities.retailNoise],
                       ['不明', scout.flowInference.probabilities.unconfirmed]] as [string, number][])
                      .filter(([, v]) => v > 0)
                      .map(([k, v]) => (
                        <span className="scout__flow-prob" key={k}>{k} {Math.round(v * 100)}%</span>
                      ))}
                  </div>
                  <div className="scout__flow-next">次の確認: {scout.flowInference.nextConditionJa}</div>
                </div>
              )}
              {scout.catalystContext && scout.catalystContext.items.length > 0 && (
                <div className="scout__cat">
                  <div className="scout__cat-head">📰 材料(参考)</div>
                  <ul className="scout__reasons">
                    {scout.catalystContext.items.map((it, i) => (
                      <li key={i}>
                        {it.kind === 'news' && `ニュース: ${it.labelJa}が${it.level === 'high' ? '高水準' : '増加'}(${it.count}件)${it.headline ? ` 「${it.headline}」` : ''}`}
                        {it.kind === 'link' && `${it.labelJa}: ${it.noteJa}`}
                        {it.kind === 'regime' && `${it.labelJa}: ${it.noteJa}`}
                        {it.kind === 'event' && `${it.labelJa}: ${it.noteJa}`}
                        {it.kind === 'earnings' && `${it.labelJa}: ${it.noteJa}`}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {scout.metrics && (
                <div className="scout__metrics">
                  RSI14 {scout.metrics.rsi14}・25日線乖離 {scout.metrics.ma25DiffPct ?? '—'}%・5日 {scout.metrics.ret5 ?? '—'}%・20日 {scout.metrics.ret20 ?? '—'}%
                  {scout.flow?.bigNetRatio != null && <>・大口 {(scout.flow.bigNetRatio * 100).toFixed(0)}%{scout.flow.ageMin != null && scout.flow.ageMin > 30 ? `(${Math.round(scout.flow.ageMin / 60)}h前)` : ''}</>}
                </div>
              )}
              <div className="scout__gaps">
                未対応(正直表示): {(scout.dataGapsJa ?? []).join(' / ')}
              </div>
              <div className="scout__note">{scout.noteJa}</div>
            </div>
          )}
          <div className="asset-detail__note">
            <span className="asset-detail__k">📝 リサーチメモ(Gemini/GPTの回答を貼り付け・端末内/同期)</span>
            <textarea
              className="asset-detail__note-area"
              value={note}
              placeholder="Gemini OSINTの結論などをここに保存…"
              onChange={(e) => { setNote(e.target.value); setNoteSaved(false); }}
              onBlur={() => { saveNote(asset.symbol, note); setNoteSaved(true); }}
            />
            {noteSaved && <span className="asset-detail__note-saved">✓ 保存</span>}
          </div>
          <div className="asset-detail__foot">
            <span>updated {ageMin(strat.lastUpdated)}</span>
            <span className="asset-detail__actions">
              {(asset.market === 'JP' || asset.market === 'US') && (
                <button className="asset-mini" onClick={runScout} disabled={scout === 'loading'}
                        title="60日トレンド・過熱度・大口フロー・イベント接近を束ねた入りの瞬間診断">
                  {scout === 'loading' ? '診断中…' : '⚡ エントリー診断'}
                </button>
              )}
              <button className="asset-mini" aria-label={`Copy ${asset.symbol} consult prompt for an LLM`}
                      title="Gemini/GPTに相談するプロンプトをコピー。フロー・信用需給・ARGUS校正実績を先頭に置いたモート起点プロンプト(先に⚡診断を押すと中身が濃くなります)"
                      onClick={copyLlmConsult}>
                {llmCopied ? '✓ Copied' : '🧠 AI相談'}
              </button>
              <button className="asset-mini asset-mini--danger" aria-label={`Remove ${asset.symbol}`} onClick={() => onRemove(asset.id)}>Remove</button>
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

export const AssetStrategySection: React.FC<Props> = ({ assets, onReorder, expandedId, onToggleExpand, onRemove, onUpdateHolding }) => {
  useLocale();   // re-render on locale switch
  const rates = useRatesSnapshot();
  const usdJpy = rates.data?.usdJpy?.latestValue ?? null;
  // Cached AI judgment (read-only — never triggers a run). Per-symbol views
  // appear in the cards while the cache is fresh (daily cron / admin run).
  const aiJ = useAIJudgment();
  const aiBySym = useMemo(() => {
    const m = new Map<string, AIJudgmentLabel>();
    if (aiJ.data && (aiJ.data.status === 'live' || aiJ.data.status === 'partial')) {
      for (const l of aiJ.data.labels) m.set(l.symbol, l);
    }
    return m;
  }, [aiJ.data]);
  // Honest freshness: the AI view is a snapshot of the last admin/cron run,
  // not a continuously-thinking model. Show its age on every block.
  const aiAgeMin = useMemo(() => {
    const t = aiJ.data?.asOf ? Date.parse(aiJ.data.asOf) : NaN;
    return Number.isFinite(t) ? Math.max(0, Math.round((Date.now() - t) / 60000)) : null;
  }, [aiJ.data]);
  // Dynamic mode: the engine follows the USER's actual assets — symbols added
  // via the UI get live quotes AND rule labels (no longer the fixed 11).
  const jpSyms = useMemo(() => assets.filter((a) => a.market === 'JP').map((a) => a.symbol), [assets]);
  const usSyms = useMemo(() => assets.filter((a) => a.market === 'US').map((a) => a.symbol), [assets]);
  const jp = useJapanWatchlist(jpSyms);
  const us = useUSWatchlist(usSyms);
  const al = useActionLabels({ jp: jpSyms, us: usSyms });
  const cat = useCatalysts();
  const { data: downside } = useDownsideIncidents();
  const { funds: navFunds } = useFundNav();   // 投信 基準価額(NAV) — show it in the list too (v10.111)
  // Crypto quotes via CoinGecko: each crypto asset stores its id in the memo
  // as "coingecko:<id>" (the seed assets and symbol-search both do this).
  const cryptoPairs = useMemo(
    () => assets
      .filter((a) => a.market === 'CRYPTO')
      .map((a) => ({ symbol: a.symbol, id: coingeckoIdOf(a) }))
      .filter((p) => p.id),
    [assets],
  );
  const cryptoIds = useMemo(() => cryptoPairs.map((p) => p.id), [cryptoPairs]);
  const crypto = useCryptoWatchlist(cryptoIds);
  const mountTs = useMemo(() => Date.now(), []);  // stable per mount/rescan
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const maps = useMemo(() => {
    const quotes = new Map<string, QuoteLite>();
    // Carry the live snapshot `name` (三菱商事 etc.) so code-only restored rows self-heal (v10.206).
    for (const s of jp.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status, flow: s.flow ?? null, name: s.name });
    for (const s of us.data?.stocks ?? []) quotes.set(s.symbol, { price: s.price, changePct: s.changePct, volume: s.volume, date: s.date, status: s.status, flow: s.flow ?? null, name: s.name });
    for (const p of cryptoPairs) {
      const q = crypto.byId[p.id];
      if (q) quotes.set(p.symbol, { price: q.priceUsd, changePct: q.changePct, volume: q.volume, date: q.date, status: q.status });
    }
    const labels = new Map<string, ActionLabel>();
    for (const l of al.data?.labels ?? []) labels.set(l.symbol, l);
    const cats = new Map<string, CatalystItem>();
    for (const c of cat.data?.items ?? []) cats.set(c.symbol, c);
    const downsideBySym = new Map<string, DownsideIncident>();
    for (const inc of downside?.incidents ?? []) downsideBySym.set(inc.symbol, inc);
    // 投信(基準価額): match each fund asset to a catalog NAV by symbol/name so the
    // Watchlist shows ¥NAV + 前日比 (was only on Core Portfolio before, v10.111).
    const navByName = (a: AssetItem) => {
      const sym = (a.symbol || '').toUpperCase();
      const nm = `${a.displayName || ''} ${a.displayNameJa || ''}`.toLowerCase();
      const want = (kw: string) => sym.includes(kw) || nm.includes(kw.toLowerCase());
      for (const f of navFunds) {
        const fn = (f.name || '').toLowerCase();
        if (fn.includes('全世界') && (want('ACWI') || nm.includes('全世界') || nm.includes('オルカン') || nm.includes('オール'))) return f;
        if (fn.includes('s&p500') && (want('SP500') || want('S&P') || nm.includes('米国'))) return f;
        if (fn.includes('国内') && (want('N225') || want('NIKKEI') || nm.includes('国内') || nm.includes('日経'))) return f;
      }
      return null;
    };
    for (const a of assets) {
      if (genreOf(a) === 'funds') {
        const f = navByName(a);
        if (f) quotes.set(a.symbol, { price: f.navYen, changePct: f.changePct ?? 0, volume: 0, date: f.date, status: 'live' });
      }
    }
    return { quotes, labels, cats, downsideBySym };
  }, [jp.data, us.data, al.data, cat.data, crypto.byId, cryptoPairs, downside, navFunds, assets]);

  // Portfolio exposure — value holdings at the last known price (live OR delayed close),
  // not just live. Otherwise a closed market (e.g. JP after 15:30) makes its holdings
  // "unpriced" so its currency total vanishes — the bug where only USD showed until the
  // JP session opened. Only MOCK prices are excluded. Shared by Exposure + What-if.
  const exp = useMemo(
    () => buildExposure(assets, (a) => {
      const q = maps.quotes.get(a.symbol);
      return q && q.status !== 'mock' && Number.isFinite(q.price) ? q.price : undefined;
    }, usdJpy),
    [assets, maps.quotes, usdJpy],
  );

  // Group by genre (GENRES order), each sorted by sortOrder ascending.
  const groups = useMemo(() => {
    return GENRES.map((g) => ({
      ...g,
      items: assets.filter((a) => genreOf(a) === g.key).slice().sort((a, b) => a.sortOrder - b.sortOrder),
    })).filter((g) => g.items.length > 0);
  }, [assets]);

  // Risk-day filter (v10.106): "今、危ないものだけ見せろ". 'risk' = in an active
  // downside incident; 'held' = a position you actually hold (qty>0).
  const [filter, setFilter] = useState<'all' | 'risk' | 'held'>('all');
  const riskCount = useMemo(
    () => assets.filter((a) => maps.downsideBySym.has(a.symbol)).length,
    [assets, maps.downsideBySym],
  );
  const filteredGroups = useMemo(() => {
    if (filter === 'all') return groups;
    const keep = (a: AssetItem) => filter === 'risk'
      ? maps.downsideBySym.has(a.symbol)
      : (a.quantity ?? 0) > 0;
    return groups.map((g) => ({ ...g, items: g.items.filter(keep) })).filter((g) => g.items.length > 0);
  }, [groups, filter, maps.downsideBySym]);

  const connecting = jp.phase === 'connecting' && us.phase === 'connecting';

  function onDragEnd(groupIds: string[]) {
    return (e: DragEndEvent) => {
      if (filter !== 'all') return;   // reorder disabled while filtered (partial subset)
      const { active, over } = e;
      if (!over || active.id === over.id) return;
      const from = groupIds.indexOf(String(active.id));
      const to = groupIds.indexOf(String(over.id));
      if (from < 0 || to < 0) return;
      onReorder(arrayMove(groupIds, from, to));
    };
  }

  if (assets.length === 0) {
    return <div className="card asset-list"><div className="asset-empty">資産がありません。「+ Add Asset」で追加できます。</div></div>;
  }

  const cal = al.data?.calibration;

  return (
    <div className="asset-groups">
      <ExposureCard assets={assets} exp={exp} />
      <WhatIfPanel assets={assets} quotes={maps.quotes} labels={maps.labels} cats={maps.cats}
                   exp={exp} usdJpy={usdJpy} mountTs={mountTs} />
      {cal && (
        <div className="asset-calibration" title="予測台帳の採点成績が確信度に反映されます(calibration-v1)">
          🎯 校正: {cal.basisJa}
        </div>
      )}
      {connecting && <div className="asset-empty asset-empty--card">connecting… 最新の戦略を取得中</div>}
      <div className="asset-filter">
        <button className={`asset-filter__chip${filter === 'all' ? ' is-active' : ''}`} onClick={() => setFilter('all')}>{t('wl.filterAll')}</button>
        <button className={`asset-filter__chip asset-filter__chip--risk${filter === 'risk' ? ' is-active' : ''}`} onClick={() => setFilter('risk')}>
          {t('wl.filterDanger')}{riskCount > 0 ? ` (${riskCount})` : ''}
        </button>
        <button className={`asset-filter__chip${filter === 'held' ? ' is-active' : ''}`} onClick={() => setFilter('held')}>{t('wl.filterHeld')}</button>
        {filter !== 'all' && <span className="asset-filter__note">{t('wl.filterNoReorder')}</span>}
      </div>
      {filteredGroups.length === 0 && filter !== 'all' && (
        <div className="asset-empty asset-empty--card">
          {filter === 'risk' ? t('wl.noDanger') : t('wl.noHeld')}
        </div>
      )}
      {filteredGroups.map((g) => {
        const ids = g.items.map((a) => a.id);
        return (
          <section className="asset-group" key={g.key}>
            <div className="asset-group__title">{g.title}<span className="asset-group__count">{g.items.length}</span></div>
            <div className="card asset-list">
              <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd(ids)}>
                <SortableContext items={ids} strategy={verticalListSortingStrategy}>
                  {g.items.map((a) => {
                    const q = maps.quotes.get(a.symbol);
                    const strat = deriveStrategy(a, maps.labels.get(a.symbol), q, maps.cats.get(a.symbol), mountTs);
                    return (
                      <SortableAssetRow
                        key={a.id} asset={a} strat={strat} liveName={q?.name ?? undefined} expanded={expandedId === a.id}
                        onToggleExpand={onToggleExpand} onRemove={onRemove}
                        onUpdateHolding={onUpdateHolding}
                        aiLabel={aiBySym.get(a.symbol)}
                        aiAgeMin={aiAgeMin}
                        incident={maps.downsideBySym.get(a.symbol)}
                      />
                    );
                  })}
                </SortableContext>
              </DndContext>
            </div>
          </section>
        );
      })}
    </div>
  );
};
