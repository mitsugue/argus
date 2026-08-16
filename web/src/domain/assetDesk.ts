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
  signalCode?: string | null;
  actionOverride?: string | null;
  ownerLabel?: string | null;
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
}

export interface PortfolioCommandView {
  primaryCommandJa: string;
  supportingSummaryJa: string;
  counters: Array<{ key: 'new-stop' | 'exit-watch' | 'inspect' | 'hold';
    labelJa: string; count: number }>;
}

const ACTION_JA: Record<string, { held: string; watch: string; entry: string }> = {
  EXIT: { held: '撤退を検討', watch: '新規停止', entry: '新規停止' },
  DEFEND: { held: '縮小・防衛を検討', watch: '新規停止', entry: '新規停止' },
  REVIEW: { held: '保有を再点検', watch: '要点検・新規停止', entry: '新規停止' },
  PAUSE: { held: '保有継続・状況待ち', watch: '待機・新規停止', entry: '新規停止' },
  HOLD_ONLY: { held: '保有継続・買い増し禁止', watch: '新規停止', entry: '新規停止' },
  PREPARE: { held: '保有継続・条件待ち', watch: '条件待ち', entry: '条件成立まで待機' },
  ENTER: { held: '保有継続・追加可', watch: '条件内で新規可', entry: '条件内で新規可' },
};

const OVERRIDE_JA: Record<string, string> = {
  EXIT_WATCH: '撤退検討', TRIM_WATCH: '縮小検討', REVIEW_REQUIRED: '要点検',
  DO_NOT_ADD: '買い増し禁止', HOLD_CAUTION: '警戒して保有', WAIT: '待機',
};

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
  const canonical = input.canonicalPrimaryAction
    ? CANONICAL_ACTION[input.canonicalPrimaryAction] : null;
  const signalCode = canonical?.signalCode ?? (input.signalCode && ACTION_JA[input.signalCode]
    ? input.signalCode : 'PAUSE');
  const action = ACTION_JA[signalCode];
  const override = !canonical && input.actionOverride
    ? OVERRIDE_JA[input.actionOverride] ?? compactDecisionText(input.actionOverride, 24)
    : null;
  const currentActionJa = canonical
    ? (input.held ? canonical.held : canonical.watch)
    : override || (input.held ? action.held : action.watch);
  const used = new Set<string>([decisionSemanticKey(currentActionJa)].filter(Boolean));
  const guardedOwnerAction = override
    || (['EXIT', 'DEFEND', 'REVIEW'].includes(signalCode) ? action.held : null);
  const ownerActionJa = canonical ? (input.held ? canonical.held : '監視のみ（保有なし）')
    : input.held
    // An incident override is authoritative. Keeping an older position stance
    // here could display "撤退検討" and "保有継続" in the same DecisionView.
    ? guardedOwnerAction || compactDecisionText(input.ownerLabel, 42) || action.held
    : '監視のみ（保有なし）';
  const entryActionJa = canonical?.entry ?? (override ? '新規停止' : action.entry);
  const whyJa = firstDistinct(input.whyCandidates, used, '検証済みの個別理由なし');
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
    primaryAction: input.canonicalPrimaryAction ?? currentActionJa,
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
