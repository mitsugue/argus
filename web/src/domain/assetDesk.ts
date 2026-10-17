// V12.2.12 — Asset Desk 純view-model(デフォルト並び順)。
//
// 「今日見るべき銘柄が上」の決定論ソート: 新しい判断は生成せず、既存レイヤー
// (シグナル/優先度/リスク/incident/AIとルールの不一致/イベント接近)の出力
// だけで順位を決める。同順位はsymbol昇順 — 入力順に依存しない(順序不変)。

import {
  normalizeDataState,
  semanticDecisionKey,
  type DataState,
  type DecisionView,
  type EvidenceState,
} from './decisionView';
import type { LiveQuote } from './liveQuote';
import type { PrimaryAction } from './singleDecisionAuthority';

export type DeskGenre = 'jp' | 'us' | 'funds' | 'crypto';

export interface DecisionFirstInput {
  symbol: string;
  name: string;
  market: string;
  held: boolean;
  /** Sole five-action authority. Legacy signal/override fields below are evidence only. */
  canonicalPrimaryAction?: PrimaryAction | null;
  canonicalDecisionId?: string | null;
  canonicalDecisionStatus?: 'EVALUATED' | 'DATA_GATED' | null;
  canonicalConfidenceBps?: number | null;
  sevenSignStatus?: 'PRODUCTION' | 'SHADOW' | 'DATA_GATED' | null;
  sevenSignLevel?: number | null;
  targets?: Array<{ value: string; unit: string }>;
  invalidation?: { value: string; unit: string } | null;
  freshness?: string | null;
  priceText: string;
  changePct?: number | null;
  pnlPct?: number | null;
  priority: string;
  dataStatus: string;
  evidenceState?: EvidenceState;
  asOf?: string | null;
  quoteTruth?: LiveQuote | null;
  rank: number;
  whyCandidates: Array<string | null | undefined>;
  nextCandidates: Array<string | null | undefined>;
  changeCandidates: Array<string | null | undefined>;
}

export interface DecisionFirstView extends DecisionView {
  symbol: string;
  name: string;
  market: string;
  held: boolean;
  signalCode: string;
  currentActionJa: string;
  ownerActionJa: string;
  entryActionJa: string;
  whyJa: string;
  nextJa: string;
  whatChangesJa: string;
  priceText: string;
  changePct: number | null;
  pnlPct: number | null;
  priority: string;
  dataStatus: string;
  dataState: DataState;
  evidenceState: EvidenceState;
  asOf: string | null;
  quoteTruth: LiveQuote | null;
  rank: number;
  bucket: 'exit-watch' | 'inspect' | 'hold' | 'new-stop';
  canonicalDecisionId: string | null;
  canonicalDecisionStatus: 'EVALUATED' | 'DATA_GATED' | null;
  canonicalPrimaryAction: PrimaryAction | null;
  canonicalConfidenceBps: number | null;
  sevenSignStatus: 'PRODUCTION' | 'SHADOW' | 'DATA_GATED' | null;
  sevenSignLevel: number | null;
  targets: Array<{ value: string; unit: string }>;
  invalidation: { value: string; unit: string } | null;
  freshness: string | null;
}

export interface PortfolioCommandView {
  primaryCommandJa: string;
  supportingSummaryJa: string;
  counters: Array<{ key: 'new-stop' | 'exit-watch' | 'inspect' | 'hold';
    labelJa: string; count: number }>;
}

const CANONICAL_ACTION: Record<PrimaryAction, {
  signalCode: string; held: string; watch: string; entry: string;
}> = {
  BUY: { signalCode: 'ENTER', held: 'BUY（追加可）', watch: 'BUY', entry: 'BUY' },
  HOLD: { signalCode: 'HOLD_ONLY', held: 'HOLD（保有継続）', watch: 'HOLD', entry: '新規なし' },
  WAIT: { signalCode: 'PAUSE', held: 'WAIT（保有判断を保留）', watch: 'WAIT', entry: 'WAIT' },
  REDUCE: { signalCode: 'DEFEND', held: 'REDUCE（縮小）', watch: 'WAIT', entry: '新規停止' },
  EXIT: { signalCode: 'EXIT', held: 'EXIT（撤退）', watch: 'WAIT', entry: '新規停止' },
};

export function compactDecisionText(value: string | null | undefined,
                                    maxLength = 70): string | null {
  const clean = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!clean) return null;
  return clean.length <= maxLength ? clean : `${clean.slice(0, maxLength - 1)}…`;
}

/** 同義の結論を別sectionで繰り返さないための表示用semantic key。 */
export const decisionSemanticKey = semanticDecisionKey;

function firstDistinct(candidates: Array<string | null | undefined>,
                       used: Set<string>, fallback: string) {
  for (const candidate of candidates) {
    const line = compactDecisionText(candidate);
    if (!line) continue;
    // Internal resolver codes are audit metadata, not owner instructions.
    // They remain available in data-quality evidence but never leak into the
    // one-screen command surface.
    if (!/[ぁ-んァ-ヶ一-龠]/.test(line)
        && /[._:]/.test(line)
        && /^[a-z0-9._:-]+$/i.test(line)) continue;
    const key = decisionSemanticKey(line);
    const seenTokens = new Set([...used].flatMap((item) => item.split(':')));
    const candidateTokens = key.split(':').filter(Boolean);
    if (candidateTokens.length > 0
        && candidateTokens.every((token) => seenTokens.has(token))) continue;
    if (key) used.add(key);
    return line;
  }
  return fallback;
}

export function buildDecisionFirstView(input: DecisionFirstInput): DecisionFirstView {
  const canonicalAction = input.canonicalPrimaryAction ?? 'WAIT';
  const canonical = CANONICAL_ACTION[canonicalAction];
  const signalCode = canonical.signalCode;
  const currentActionJa = input.held ? canonical.held : canonical.watch;
  const used = new Set<string>([decisionSemanticKey(currentActionJa)].filter(Boolean));
  const ownerActionJa = input.held ? canonical.held : '監視のみ（保有なし）';
  const entryActionJa = canonical.entry;
  const whyJa = firstDistinct(input.whyCandidates, used, '判断に必要な個別データを確認中');
  const nextJa = firstDistinct(
    input.nextCandidates, used, '個別開示・出来高・同業差を確認');
  const whatChangesJa = firstDistinct(
    input.changeCandidates, used, '新しい確認済み材料で再判定');
  const bucket: DecisionFirstView['bucket'] =
    signalCode === 'EXIT' || signalCode === 'DEFEND' || /撤退|縮小/.test(currentActionJa)
      ? 'exit-watch'
      : input.rank <= 5 || /点検|確認/.test(currentActionJa)
        ? 'inspect'
        : input.held ? 'hold' : 'new-stop';
  const dataState = normalizeDataState(input.dataStatus);
  const evidenceState = input.evidenceState
    ?? (whyJa === '判断根拠データを確認中' ? 'UNRESOLVED'
      : dataState === 'STALE' ? 'STALE'
        : dataState === 'UNAVAILABLE' ? 'UNAVAILABLE' : 'SUPPORTED_HYPOTHESIS');
  return {
    symbol: input.symbol, name: input.name, market: input.market, held: input.held,
    signalCode, currentActionJa, ownerActionJa, entryActionJa,
    whyJa, nextJa, whatChangesJa, priceText: input.priceText,
    changePct: input.changePct ?? null, pnlPct: input.pnlPct ?? null,
    priority: input.priority, dataStatus: input.dataStatus, rank: input.rank,
    bucket,
    primaryAction: canonicalAction,
    ownerAction: ownerActionJa,
    entryAction: entryActionJa,
    reason: whyJa,
    nextCheck: nextJa,
    changeCondition: whatChangesJa,
    evidenceState,
    dataState,
    asOf: input.asOf ?? null,
    quoteTruth: input.quoteTruth ?? null,
    canonicalDecisionId: input.canonicalDecisionId ?? null,
    canonicalDecisionStatus: input.canonicalDecisionStatus ?? null,
    canonicalPrimaryAction: canonicalAction,
    canonicalConfidenceBps: input.canonicalConfidenceBps ?? null,
    sevenSignStatus: input.sevenSignStatus ?? null,
    sevenSignLevel: input.sevenSignLevel ?? null,
    targets: input.targets ?? [],
    invalidation: input.invalidation ?? null,
    freshness: input.freshness ?? null,
  };
}

export function buildPortfolioCommand(views: DecisionFirstView[]): PortfolioCommandView {
  const count = (bucket: DecisionFirstView['bucket']) =>
    views.filter((view) => view.bucket === bucket).length;
  const first = views[0];
  return {
    primaryCommandJa: first
      ? `最優先：${first.symbol} ${first.name} — ${first.nextJa}`
      : '最優先：保有・監視資産の判断データを確認中',
    supportingSummaryJa: views.length
      ? `${views.length}資産を優先度順に整理。判断変更条件は各銘柄で確認。`
      : '登録資産はありません。',
    counters: [
      { key: 'new-stop', labelJa: '新規停止', count: count('new-stop') },
      { key: 'exit-watch', labelJa: '撤退・縮小', count: count('exit-watch') },
      { key: 'inspect', labelJa: '要点検', count: count('inspect') },
      { key: 'hold', labelJa: '保有継続', count: count('hold') },
    ],
  };
}

export interface DeskRankInput {
  symbol: string;
  genre: DeskGenre;
  held: boolean;
  /** actionLevelのSignalCode(EXIT/DEFEND/...)。不明はundefined。 */
  signalCode?: string | null;
  /** ACTION PRIORITYのrank(P0/P1/P2/Watch/Ignore)。 */
  apRank?: string | null;
  /** positionExposureのriskLevel(low/medium/high/critical)。 */
  positionRiskLevel?: string | null;
  hasIncident: boolean;
  /** AI主判断とルール判定のアクション不一致。 */
  aiRuleDisagree: boolean;
  /** 重要イベントD/D-1に紐づく。 */
  eventSoon: boolean;
}

// 小さいほど上。仕様§8の順序を固定番号で表現(表示グループ名にも使う)。
export const DESK_RANK_JA: Record<number, string> = {
  0: '保有 × 撤退/防衛',
  1: '保有 × P0',
  2: '保有 × P1/高リスク',
  3: '急落対応中',
  4: 'AIとルールの不一致',
  5: 'イベント接近',
  6: 'その他の保有',
  7: '監視(株)',
  8: '投信',
  9: '暗号資産',
};

export function deskRank(i: DeskRankInput): number {
  if (i.held && (i.signalCode === 'EXIT' || i.signalCode === 'DEFEND')) return 0;
  if (i.held && i.apRank === 'P0') return 1;
  if (i.held && (i.apRank === 'P1'
    || i.positionRiskLevel === 'high' || i.positionRiskLevel === 'critical')) return 2;
  if (i.hasIncident) return 3;
  if (i.aiRuleDisagree) return 4;
  if (i.eventSoon) return 5;
  if (i.held) return 6;
  if (i.genre === 'jp' || i.genre === 'us') return 7;
  if (i.genre === 'funds') return 8;
  return 9;
}

/** 決定論ソート: rank昇順→symbol昇順。入力順に依存しない(防御コピー)。 */
export function sortDesk<T extends { rankInput: DeskRankInput }>(items: T[]): (T & { rank: number })[] {
  return items
    .map((it) => ({ ...it, rank: deskRank(it.rankInput) }))
    .sort((a, b) => a.rank - b.rank
      || (a.rankInput.symbol < b.rankInput.symbol ? -1 : a.rankInput.symbol > b.rankInput.symbol ? 1 : 0));
}
