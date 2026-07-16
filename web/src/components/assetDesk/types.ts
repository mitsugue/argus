// V12.2.12 Asset Desk — カード1枚に渡すデータ束(組み立てはAssetDeskList)。
// この層は表示のみ: 判断はdomain/assetDecision(正本)とuseAssetIntelの出力を
// そのまま受け取る。新しい投資判断は生成しない。
import type { AssetItem } from '../../types/assetItem';
import type { AssetCardModel } from '../../domain/assetCard';
import type { AssetDecisionView, AiMeta } from '../../domain/assetDecision';
import type { AssetStrategy, QuoteLite } from '../../lib/assetStrategy';
import type { HolderPosture } from '../../lib/holderPosture';
import type { DownsideIncident } from '../../hooks/useDownsideIncidents';
import type { PositionNote } from '../../domain/positionExposure';
import type { SupplyDemandSignal } from '../../hooks/useSupplyDemand';
import type { APItem } from '../../domain/actionPriority';
import type { LocalScenarioSet } from '../../domain/scenario';
import type { LocalPlan } from '../../domain/positionPlan';
import type { ResolvedStance } from '../../domain/primaryStance';
import type { AIJudgmentLabel } from '../../types/aiJudgment';
import type { DeskGenre } from '../../domain/assetDesk';

export interface DeskEventTag { code: string; countdown: string; impact: string }

export interface DeskCardData {
  asset: AssetItem;
  genre: DeskGenre;
  rank: number;
  /** JP/US/CRYPTOのみ(Todayと同じgroupAssetCards出力)。投信はundefined。 */
  card?: AssetCardModel;
  /** 判断の正本ビュー(JP/US)。AI対象外クラスはundefined。 */
  decision?: AssetDecisionView;
  strat: AssetStrategy;
  quote?: QuoteLite;
  liveName?: string | null;
  incident?: DownsideIncident;
  hp: HolderPosture | null;
  pn?: PositionNote;
  sdg?: SupplyDemandSignal;
  apx?: APItem;
  scn?: LocalScenarioSet;
  ppl?: LocalPlan;
  pst?: ResolvedStance;
  aiLabel?: AIJudgmentLabel;
  aiAgeMin: number | null;
  aiMeta: AiMeta;
  eventTags: DeskEventTag[];
}

/** 展開セクションid(deep-linkのsection指定と対応・§7の順序)。 */
export const DESK_SECTIONS = [
  'decision', 'ai-review', 'owner-position', 'why-downside', 'flow-supply',
  'events', 'technical', 'scenarios', 'research', 'data-quality',
] as const;
export type DeskSection = (typeof DESK_SECTIONS)[number];

export const sectionAnchorId = (symbol: string, section?: DeskSection | string) =>
  section ? `ad-${symbol.toUpperCase()}-${section}` : `asset-${symbol.toUpperCase()}`;
