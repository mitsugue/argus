// V11.20.0 — Pro Handoff 2.0 / AI Review Pack (device-local TS port of
// argus_review_pack.py). GPT Pro/Gemini/Claudeに貼るセカンドオピニオン用パックを
// 全レイヤーから重複なく合成する。外部AIへの自動送信なし・サーバー保存なし・
// 秘密ゼロ・執行語ゼロ。売買指示ではなくレビュー依頼の文書。

import { latestExposure, latestActionPriorities, latestSessionBrief,
  latestScenarios, latestPlans, latestStrategy, latestFireCore,
  latestDataQuality, latestOsint, latestOsintDeep } from './positionExposureShare';
import { listNotifications } from './notifications';
import { assessBackupSafety } from './backupSafety';
import { jpDisplay } from './displayName';

export type PackType = 'daily' | 'asset' | 'portfolio' | 'event' | 'emergency' | 'osint';
export type PrivacyMode = 'redacted' | 'owner_copy';
export type PackLength = 'full' | 'short';

export const PACK_PRIVACY_LABEL_JA =
  'この内容には個人投資情報が含まれる可能性があります。共有先に注意してください。';
const REDACTED_LABEL_JA = '(redactedモード: 個人投資情報は除外済み — ウォッチリスト水準のみ)';
const COMPLIANCE_JA = 'これはセカンドオピニオン用のレビュー資料であり、売買指示・自動売買・免許業の助言ではない。外部AIへの自動送信はしない。';

const PRIVATE_MARKERS = ['保有中', '含み益', '含み損', '取得単価', '口数', '積立',
  '評価額', '全体の', '比率が高', 'NISA', 'iDeCo', '保有・'];

const INSTRUCTIONS_JA: Record<PackType, string> = {
  daily: 'あなたは経験豊富な投資リスクレビュアーです。以下のARGUS出力を前提に、売買指示ではなく、判断の弱点・反対シナリオ・不足データ・確認すべき条件を日本語で整理してください。ARGUSの結論をそのまま肯定せず、特に過剰に楽観/悲観になっている点を指摘してください。',
  asset: 'この銘柄について、ARGUSの判断の弱点と見落としを中心にレビューしてください。特に「入っていいか/待つべきか」の分岐条件が妥当か、需給・フロー解釈に代替説明がないかを検討してください。売買指示は不要です。',
  portfolio: 'ポートフォリオ構成とFIRE整合について、集中リスク・コア/戦術枠のバランス・不足データの影響を中心にレビューしてください。数値は概算・帯であり、退職時期や確率の計算は求めません。売買指示は不要です。',
  event: 'このイベントについて、ARGUSの事前シナリオの弱点・見落としている波及経路・発表後に真っ先に確認すべき指標を整理してください。売買指示は不要です。',
  emergency: '保有銘柄に複合リスク信号が出ています。ARGUSの判断が過剰反応か過小反応か、いま確認すべき事実の優先順位、やってはいけない行動を整理してください。パニック的な即断を勧めないでください。売買指示は不要です。',
  osint: 'あなたはOSINT(公開情報)調査のレビュアーです。以下の候補原因について、公式開示・主要ニュース・セクター/テーマ連想を分けて妥当性を検証し、ARGUSが見逃している強い材料がないかを指摘してください。弱い連想を事実として扱わないでください。売買指示は不要です。',
};
const QUESTIONS_JA: Record<PackType, string> = {
  daily: '今日の全体をプロ目線でレビューしてほしい。ARGUSの見落としはないか。',
  asset: 'この銘柄、ARGUSの判断は合っているか。弱点を中心に見てほしい。',
  portfolio: 'この構成でFIRE計画として無理はないか。集中しすぎていないか。',
  event: 'このイベントの前後で何を確認すべきか。ARGUSの事前シナリオに穴はないか。',
  emergency: '保有銘柄に警報が出た。冷静に、何を確認しどう構えるべきか。',
  // v12.0.8 Part F: 外部AIへのOSINT診断依頼(コピー専用・自動送信なし)
  osint: 'この下落/上昇要因について、ARGUSの候補原因が妥当か、他に強いニュースがないか、公式開示・主要ニュース・セクター連想を分けて検証してください。',
};

export interface PackEventInfo {
  code: string; titleJa: string; stateJa: string; whyJa?: string;
  linkedAssets: string[]; checksAfterJa?: string[];
}

export interface PackOptions {
  packType: PackType;
  privacyMode: PrivacyMode;
  length: PackLength;
  appVersion: string;
  symbol?: string;              // asset pack
  event?: PackEventInfo;        // event pack
  eventsJa?: string[];          // daily: Important Events一行群(重複はここで1回のみ)
  serverContextMd?: string;     // full dailyのみ: サーバーのwatchlist文脈を末尾に添付
}

const strip = (redacted: boolean, lines: string[]): string[] =>
  redacted ? lines.filter((x) => !PRIVATE_MARKERS.some((m) => x.includes(m))) : lines;

/** パックを合成してmarkdownを返す(端末内のみ・送信なし)。 */
export function buildReviewPackMarkdown(o: PackOptions): string {
  const redacted = o.privacyMode === 'redacted';
  const now = new Date().toISOString().slice(0, 16).replace('T', ' ');
  const brief = latestSessionBrief();
  const aps = latestActionPriorities();
  const scenarios = latestScenarios();
  const plans = latestPlans();
  const strategy = latestStrategy();
  const fireCore = latestFireCore();
  const pe = latestExposure();

  const planBySym = new Map(plans.map((p) => [p.symbol, p]));
  const scBySym = new Map(scenarios.map((s) => [s.symbol, s]));

  // ── 対象銘柄の選定(銘柄別詳細はAssets欄に1回だけ) ─────────────────────────
  let focus = [...new Set([
    ...aps.filter((i) => ['P0', 'P1', 'P2'].includes(i.priorityRank)).map((i) => i.symbol),
    ...plans.filter((p) => ['risk_review', 'trim_consideration', 'avoid_chase',
      'small_add_allowed', 'add_only_on_pullback'].includes(p.currentStance)).map((p) => p.symbol),
    ...plans.filter((p) => p.isHeld).map((p) => p.symbol),
  ])];
  if ((o.packType === 'asset' || o.packType === 'osint') && o.symbol) focus = [o.symbol.toUpperCase()];
  if (o.packType === 'event' && o.event) focus = o.event.linkedAssets.map((s) => s.toUpperCase());
  if (o.packType === 'emergency') {
    focus = aps.filter((i) => i.priorityRank === 'P0').map((i) => i.symbol);
    if (!focus.length) focus = plans.filter((p) => p.currentStance === 'risk_review').map((p) => p.symbol);
  }
  focus = focus.slice(0, o.length === 'short' ? 3 : 8);

  // ── Top risks / opportunities / blocked(重複は銘柄単位でまとめる) ─────────
  const topRisks = strip(redacted, [
    ...(strategy?.warningsJa ?? []),
    ...aps.filter((i) => i.priorityRank === 'P0').map((i) => `P0: ${i.titleJa}`),
    ...plans.filter((p) => ['risk_review', 'trim_consideration'].includes(p.currentStance))
      .map((p) => `${jpDisplay(p.symbol, p.assetName)}: ${p.currentStanceJa}`),
  ]).slice(0, 5);
  const topOpps = strip(redacted, [
    ...(strategy?.opportunitiesJa ?? []),
    ...plans.filter((p) => p.currentStance === 'small_add_allowed')
      .map((p) => `${jpDisplay(p.symbol, p.assetName)}: 小さく可(注意付き)`),
  ]).slice(0, 4);
  const blocked = strip(redacted, plans.filter((p) => p.planType === 'event_wait')
    .map((p) => `${jpDisplay(p.symbol, p.assetName)}: イベント待ち`)).slice(0, 5);

  const missing = strip(redacted, [...new Set([
    ...(strategy?.missingDataJa ?? []),
    ...(fireCore?.missingDataJa ?? []),
    ...scenarios.filter((s) => s.evidenceQuality === 'insufficient')
      .map((s) => `${s.symbol}: シナリオ証拠不足`),
  ])]).slice(0, 6);

  const opposing = 'ARGUSの各レイヤーは公表遅延データ(需給)と推定(フロー)に依存しており、実測フローの転換一つで支配シナリオ・計画が入れ替わり得る。結論の固定を疑うこと。' +
    (strategy && !redacted ? ' 戦略整合は入力済みデータのみの概算であり、現金・入金力次第で結論が変わる。' : '');

  // ── render ───────────────────────────────────────────────────────────────
  const L: string[] = [];
  L.push(`# ARGUS AI Review Pack (${o.packType} / ${o.length} / ${o.privacyMode})`);
  L.push(`asOf: ${now} · v${o.appVersion} · ${redacted ? REDACTED_LABEL_JA : PACK_PRIVACY_LABEL_JA}`);
  L.push('', '## Owner question', QUESTIONS_JA[o.packType]);
  if (brief) L.push('', '## Current command', `${brief.ownerModeJa}(${brief.marketStatusJa}): ${brief.headlineJa}`);
  if (topRisks.length) { L.push('', '## Top risks'); L.push(...topRisks.map((x) => `- ${x}`)); }
  if (topOpps.length && o.length === 'full') { L.push('', '## Top opportunities'); L.push(...topOpps.map((x) => `- ${x}`)); }
  if (blocked.length && o.length === 'full') { L.push('', '## Blocked decisions'); L.push(...blocked.map((x) => `- ${x}`)); }

  // Action Priority(一行群)
  const apLines = strip(redacted, aps.filter((i) => i.priorityRank !== 'Ignore').slice(0, 6)
    .map((i) => `[${i.priorityRank}] ${jpDisplay(i.symbol, i.assetName)} — ${i.actionLabelJa}`));
  if (apLines.length) { L.push('', '## Action Priority'); L.push(...apLines.map((x) => `- ${x}`)); }

  // Important Events(要約はここ1回のみ — 他セクションで繰り返さない)
  if (o.packType === 'event' && o.event) {
    L.push('', '## Important Events');
    L.push(`- ${o.event.code} ${o.event.titleJa} — ${o.event.stateJa}`);
    if (o.event.whyJa) L.push(`- なぜ重要か: ${o.event.whyJa}`);
    if (o.event.checksAfterJa?.length) L.push(`- 発表後の確認: ${o.event.checksAfterJa.join(' / ')}`);
  } else if (o.eventsJa?.length && o.length === 'full') {
    L.push('', '## Important Events');
    L.push(...o.eventsJa.slice(0, 5).map((x) => `- ${x}`));
  }

  if (o.length === 'full') {
    // Scenarios / Plans は集計のみ(銘柄別はAssets欄)
    const scAgg = `支配シナリオ: 弱気${scenarios.filter((s) => s.dominant === 'bearish').length}件 / イベント待ち${scenarios.filter((s) => s.dominant === 'wait_event').length}件 / 強気${scenarios.filter((s) => s.dominant === 'bullish').length}件 / ベース${scenarios.filter((s) => s.dominant === 'base').length}件(帯のみ・銘柄別はAssets欄)`;
    if (scenarios.length) { L.push('', '## Scenarios', scAgg); }
    const plAgg = `計画: 追いかけ注意${plans.filter((p) => p.currentStance === 'avoid_chase').length}件 / 押し目限定${plans.filter((p) => p.currentStance === 'add_only_on_pullback').length}件 / リスク確認${plans.filter((p) => ['risk_review', 'trim_consideration'].includes(p.currentStance)).length}件(指示ではない・銘柄別はAssets欄)`;
    if (plans.length) { L.push('', '## Entry / Exit Planning', plAgg); }

    if (!redacted && strategy && (o.packType !== 'asset')) {
      L.push('', '## Portfolio Strategy / FIRE Core', strategy.summaryJa, strategy.riskJa);
      if (fireCore?.positions.length) L.push(fireCore.summaryJa);
    }
    if (!redacted && pe && ['daily', 'portfolio', 'emergency'].includes(o.packType)) {
      const held = Object.values(pe.notes).filter((n) => n.held).length;
      L.push('', '## Position / Exposure',
        pe.noHoldings ? '保有数量未入力(監視のみ)。' : `保有${held}銘柄 · 集中度: ${pe.singleNameRisk ?? '不明'}`);
    }
    const dqLine = '過去判断の答え合わせは端末内記録ベース。履歴が少ない間は成績として扱わない(検証中)。';
    L.push('', '## Decision Quality / Learning', dqLine);
    // v11.22.0: データ鮮度の注意 — レビュアーが「古いデータ由来の判断」を割引けるように
    // v12.0.1: JP代替データのcaveatは常設(取得状態に依らない恒久の事実)
    L.push('', '## Data Quality / データ鮮度の注意');
    const dqc = latestDataQuality();
    if (dqc) {
      L.push(`総合: ${dqc.overallStatusJa}(古いデータのレイヤーは確度を割引いて評価してください)`);
      L.push(...dqc.topIssuesJa.slice(0, 3).map((x) => `- ${x}`));
      L.push(...dqc.expectedDisabledJa.slice(0, 2).map((x) => `- 仕様上の未取得: ${x}`));
      // v12.0.8 Part D: 部分データ時はその事実と確度上限を必ず明示
      if (dqc.overallStatus !== 'ok') {
        L.push('- 部分データ稼働中: 判断確度に上限がかかっています。JPリアルタイム復旧・イベント/機関データの更新・需給ウォームで解消されます。');
      }
    }
    // v12.0.6: JP caveatは簡潔な1行だけ(重複させない・v12.0.5の確認済み事実を維持)
    L.push('- 日本株リアルタイム/APIフル板はmoomoo側メンテナンス中(サポート確認済み・フル板契約済みで追加申込不要・復旧時期未定・復旧後はOpenD再起動・再ログイン後にret=0確認)。日本株判断は代替データ(J-Quants/Yahoo・夜間/引け後delayed・ARGUS側では意図的に無効化中)前提で評価してください。');
    const notifs = strip(redacted, listNotifications().slice(0, 3).map((n) => n.titleJa));
    if (notifs.length) { L.push('', '## Attention Changes'); L.push(...notifs.map((x) => `- ${x}`)); }
    if (!redacted && o.packType === 'daily') {
      try { const b = assessBackupSafety([]);
        if (b.protectionLevel !== 'unknown') L.push('', '## Backup(状態のみ)', `保護状態: ${b.protectionLevelJa}`);
      } catch { /* ignore */ }
    }
  }

  // v12.0.8 Part F: OSINTパック — 候補原因・見つかったソース・欠けているソース・
  // 直接材料かテーマ連想かを明示(弱い推測を事実として書かない)。
  if (o.packType === 'osint' && o.symbol) {
    const oz = latestOsint(o.symbol);
    L.push('', '## OSINT: 疑われる原因(ARGUSの候補)');
    if (oz) {
      L.push(`- 見立て: ${oz.headlineJa}`);
      L.push(`- OSINT確度: ${oz.osintConfidenceJa}(候補であり断定ではない)`);
      L.push('', '### 候補原因(カテゴリ別)');
      L.push(...oz.causes.map((cz, i) => `${i + 1}. [${cz.categoryJa}] ${cz.titleJa}(出典: ${cz.source || '不明'}) — 外れの可能性: ${cz.whyWrongJa}`));
      if (oz.sourcesMissingJa.length) {
        L.push('', '### 欠けているソース');
        L.push(...oz.sourcesMissingJa.map((x) => `- ${x}`));
      }
      L.push('', '### 検証依頼');
      L.push('- 直接材料(この銘柄固有の開示/報道)とテーマ連想(セクター/バリューチェーン)を分けて評価してください。');
      L.push('- ARGUSが見つけられていない強いニュース・公式開示があれば指摘してください。');
      // v12.1.0: 深掘りOSINT結果(カバレッジ/ベンチマーク/不一致/検証済みソース)
      const dz = latestOsintDeep(o.symbol);
      if (dz) {
        L.push('', '### 深掘りOSINT(マルチエージェント)');
        L.push(`- 結論: ${dz.summaryJa}`);
        L.push(`- 探索カバレッジ: ${dz.coverageJa} / 信頼度: ${dz.reliabilityJa}`);
        L.push(`- ベンチマーク: ${dz.benchmarkJa}`);
        // v12.1.1: 優位性メトリクス+未回収caveat
        if (dz.superiorityJa) L.push(`- OSINT優位性: ${dz.superiorityJa} — ${dz.superiorityVerdictJa ?? ''}`);
        // v12.1.3: researchPower(Gemini基準比 — 生件数では2xにならない測定)
        if (dz.researchPowerJa) L.push(`- ${dz.researchPowerJa}${dz.researchPowerVerdictJa ? ` — ${dz.researchPowerVerdictJa}` : ''}`);
        if (dz.contradictionWarningsJa?.length) L.push(`- 因果規律の警告: ${dz.contradictionWarningsJa.join(' / ')}`);
        if (dz.sourceCoverageJa) L.push(`- ソースカバレッジ: ${dz.sourceCoverageJa}`);
        if (dz.gapGroupsJa) L.push(`- ギャップ内訳: ${dz.gapGroupsJa}(優位性をブロックするのは具体未回収のみ)`);
        if (dz.verificationRatePct != null) L.push(`- ソース検証率: ${dz.verificationRatePct}%`);
        if ((dz.unresolvedCount ?? 0) > 0) L.push(`- 注意: Gemini単発に対して未回収のOSINTギャップ ${dz.unresolvedCount}件(検証されるまで証拠として扱っていません)`);
        if (dz.verifiedTitlesJa.length) L.push(`- 検証済みソース: ${dz.verifiedTitlesJa.join(' / ')}`);
        if (dz.disagreementJa.length) L.push(`- エージェント間の不一致: ${dz.disagreementJa.join(' / ')}`);
        if (dz.missingAreasJa.length) L.push(`- 不足領域: ${dz.missingAreasJa.join(' / ')}`);
      }
    } else {
      L.push('- 候補原因データ未取得(銘柄カードの原因分析を一度開いてから再コピーしてください)。');
    }
  }

  // Assets — 銘柄別詳細はここに1回だけ集約
  if (focus.length) {
    L.push('', '## Assets(銘柄別はここに1回だけ集約)');
    for (const sym of focus) {
      const p = planBySym.get(sym); const s = scBySym.get(sym);
      const name = p?.assetName ?? s?.assetName ?? '';
      const held = !redacted && (p?.isHeld ?? false);
      L.push(`### ${jpDisplay(sym, name)}${held ? ' [保有]' : ''}`);
      if (s) L.push(`- シナリオ: ${s.dominantJa} — ${s.summaryJa.slice(0, 80)}`);
      if (p) L.push(`- 計画: ${p.currentStanceJa} — ${strip(redacted, [p.summaryJa])[0]?.slice(0, 100) ?? '(redacted)'}`);
      if (p?.strategicRole && !redacted) L.push(`- 役割: ${p.strategicRole.roleJa}`);
      if (p?.whatNotToDoJa.length) L.push(`- やらないこと: ${p.whatNotToDoJa[0]}`);
      if (s?.invalidationJa.length) L.push(`- 無効化条件: ${s.invalidationJa[0]}`);
    }
  }

  if (o.packType === 'emergency') {
    L.push('', '## いま確認すること');
    const p0 = aps.filter((i) => i.priorityRank === 'P0');
    L.push(...(p0.length ? p0.map((i) => `- ${i.checkNextJa}`) : ['- 悪化信号の継続(翌営業日の戻り売り)を確認']));
    L.push('', '## やってはいけないこと');
    L.push('- パニック的な全処分・ナンピンの即断(条件と無効化条件を先に確認)');
  }

  L.push('', '## Missing Evidence');
  L.push(...(missing.length ? missing.map((x) => `- ${x}`) : ['- 特筆すべき欠落なし(各レイヤーの注意書き参照)']));
  L.push('', '## Strongest Opposing View', opposing);
  L.push('', '## Instructions for reviewer', INSTRUCTIONS_JA[o.packType]);
  L.push('', `注意: ${COMPLIANCE_JA}`);

  if (o.serverContextMd && o.length === 'full' && !redacted) {
    L.push('', '---', '## Market / Institutional Context (server watchlist-level)', o.serverContextMd);
  }
  return L.join('\n');
}

/** クリップボードへ(失敗時はfalse — 呼び出し側でtextarea fallback)。 */
export async function copyPack(md: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(md); return true; }
  catch { return false; }
}
