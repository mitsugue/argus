// V12.2.12 — Asset Desk 純view-model(デフォルト並び順)。
//
// 「今日見るべき銘柄が上」の決定論ソート: 新しい判断は生成せず、既存レイヤー
// (シグナル/優先度/リスク/incident/AIとルールの不一致/イベント接近)の出力
// だけで順位を決める。同順位はsymbol昇順 — 入力順に依存しない(順序不変)。

export type DeskGenre = 'jp' | 'us' | 'funds' | 'crypto';

export interface DecisionFirstInput {
  symbol: string;
  name: string;
  market: string;
  held: boolean;
  signalCode?: string | null;
  actionOverride?: string | null;
  ownerLabel?: string | null;
  priceText: string;
  changePct?: number | null;
  pnlPct?: number | null;
  priority: string;
  dataStatus: string;
  rank: number;
  whyCandidates: Array<string | null | undefined>;
  nextCandidates: Array<string | null | undefined>;
  changeCandidates: Array<string | null | undefined>;
}

export interface DecisionFirstView {
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
  rank: number;
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

export function compactDecisionText(value: string | null | undefined,
                                    maxLength = 70): string | null {
  const clean = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (!clean) return null;
  return clean.length <= maxLength ? clean : `${clean.slice(0, maxLength - 1)}…`;
}

/** 同義の結論を別sectionで繰り返さないための表示用semantic key。 */
export function decisionSemanticKey(value: string | null | undefined): string {
  const text = String(value ?? '').toUpperCase()
    .replace(/[・／/、。\s()[\]（）]/g, '');
  if (!text) return '';
  const keys: string[] = [];
  if (/EXIT|撤退/.test(text)) keys.push('exit');
  if (/TRIM|縮小|リスク縮小/.test(text)) keys.push('trim');
  if (/REVIEW|再点検|要点検|リスク確認/.test(text)) keys.push('review');
  if (/WAIT|PAUSE|様子見|待機|状況待ち|条件待ち/.test(text)) keys.push('wait');
  if (/HOLD|保有継続|維持/.test(text)) keys.push('hold');
  if (/新規.*(禁止|停止|見送り)|新規禁止/.test(text)) keys.push('no-entry');
  if (/(買い増し|追加).*(禁止|停止|しない)/.test(text)) keys.push('no-add');
  return keys.length ? [...new Set(keys)].sort().join(':') : text;
}

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
  const signalCode = input.signalCode && ACTION_JA[input.signalCode]
    ? input.signalCode : 'PAUSE';
  const action = ACTION_JA[signalCode];
  const override = input.actionOverride
    ? OVERRIDE_JA[input.actionOverride] ?? compactDecisionText(input.actionOverride, 24)
    : null;
  const currentActionJa = override || (input.held ? action.held : action.watch);
  const used = new Set<string>([decisionSemanticKey(currentActionJa)].filter(Boolean));
  const ownerActionJa = input.held
    ? compactDecisionText(input.ownerLabel, 42) || action.held
    : '監視のみ（保有なし）';
  const whyJa = firstDistinct(input.whyCandidates, used, '判断根拠データを確認中');
  const nextJa = firstDistinct(input.nextCandidates, used, '次の価格・材料更新を確認');
  const whatChangesJa = firstDistinct(
    input.changeCandidates, used, '価格・需給・材料の条件変化で再判定');
  return {
    symbol: input.symbol, name: input.name, market: input.market, held: input.held,
    signalCode, currentActionJa, ownerActionJa, entryActionJa: action.entry,
    whyJa, nextJa, whatChangesJa, priceText: input.priceText,
    changePct: input.changePct ?? null, pnlPct: input.pnlPct ?? null,
    priority: input.priority, dataStatus: input.dataStatus, rank: input.rank,
  };
}

export function buildPortfolioCommand(views: DecisionFirstView[]): PortfolioCommandView {
  const newStop = views.filter((view) => view.entryActionJa.includes('停止')
    || view.entryActionJa.includes('待機')).length;
  const exitWatch = views.filter((view) =>
    view.signalCode === 'EXIT' || view.signalCode === 'DEFEND'
    || /撤退|縮小/.test(view.currentActionJa)).length;
  const inspect = views.filter((view) => view.rank <= 5
    || /点検|確認/.test(view.currentActionJa)).length;
  const hold = views.filter((view) => view.held
    && view.signalCode !== 'EXIT' && view.signalCode !== 'DEFEND').length;
  const first = views[0];
  return {
    primaryCommandJa: first
      ? `最優先：${first.symbol} ${first.name} — ${first.nextJa}`
      : '最優先：保有・監視資産の判断データを確認中',
    supportingSummaryJa: views.length
      ? `${views.length}資産を優先度順に整理。判断変更条件は各銘柄で確認。`
      : '登録資産はありません。',
    counters: [
      { key: 'new-stop', labelJa: '新規停止', count: newStop },
      { key: 'exit-watch', labelJa: '撤退・縮小', count: exitWatch },
      { key: 'inspect', labelJa: '要点検', count: inspect },
      { key: 'hold', labelJa: '保有継続', count: hold },
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
