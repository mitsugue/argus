// V12.2.12 — Asset Desk 純view-model(デフォルト並び順)。
//
// 「今日見るべき銘柄が上」の決定論ソート: 新しい判断は生成せず、既存レイヤー
// (シグナル/優先度/リスク/incident/AIとルールの不一致/イベント接近)の出力
// だけで順位を決める。同順位はsymbol昇順 — 入力順に依存しない(順序不変)。

export type DeskGenre = 'jp' | 'us' | 'funds' | 'crypto';

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
