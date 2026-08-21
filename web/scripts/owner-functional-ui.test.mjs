import assert from 'node:assert/strict';
import fs from 'node:fs';

const read = (relative) => fs.readFileSync(new URL(`../${relative}`, import.meta.url), 'utf8');

const list = read('src/components/assetDesk/AssetDeskList.tsx');
const genres = read('src/types/assetItem.ts');
const summary = read('src/components/assetDesk/AssetDecisionSummary.tsx');
const details = read('src/components/assetDesk/AssetDecisionDetails.tsx');
const today = read('src/components/today/ArgusTodayPanel.tsx');
const chart = read('src/components/chart/ChartIntelligencePanel.tsx');
const newsHook = read('src/hooks/useNewsIntelligence.ts');
const notifications = read('src/lib/notifications.ts');
const vite = read('vite.config.ts');
const main = read('src/main.tsx');

const orderedGenreLabels = ['日本株', '米国株', '投資信託', '仮想通貨'];
let cursor = -1;
for (const label of orderedGenreLabels) {
  const next = genres.indexOf(`title: '${label}'`);
  assert.ok(next > cursor, `${label} must appear in owner group order`);
  cursor = next;
}
assert.doesNotMatch(list, /sortMode|AssetPortfolioCommand|DESK_RANK_JA/);
assert.match(list, /activationConstraint:\s*\{ delay:\s*450, tolerance:\s*8 \}/);
assert.match(list, /長押しで並べ替え・自動保存/);
assert.doesNotMatch(summary, /ad-prio|Calibration pending|\/7/);
assert.match(summary, /ownerActionJa|entryActionJa|currentActionJa/);
assert.match(details, /理由|次に確認すること|判断が変わる条件/);
assert.doesNotMatch(details, /検証済み目標なし|検証済み無効化条件なし/);
assert.match(today, /NEXT_REVIEW_REASON_JA/);
assert.match(today, /正本データの更新時刻を確認/);
assert.doesNotMatch(today, /<span>\{view\.canonicalDecision\.nextReviewConditionCodes\[0\]/);

assert.match(chart, /buildTodayProjection/);
assert.match(chart, /方向確率を検証できないため、チャートは表示しません/);
assert.match(chart, /参考値・未検証/);
assert.match(chart, /\['UP', 'RANGE', 'DOWN'\]/);

assert.match(newsHook, /translationStatus:\s*'translated' \| 'not_needed'/);
assert.match(notifications, /hasJapaneseText/);
assert.match(notifications, /event\.translationStatus/);

assert.match(vite, /__APP_VERSION__:\s*JSON\.stringify\(bundleVersion\)/);
assert.doesNotMatch(vite, /__APP_VERSION__:\s*'globalThis\.__ARGUS_VERSION__'/);
assert.match(vite, /argus\.bundle\.identity/);
assert.match(vite, /navigator\.serviceWorker\.getRegistrations/);
assert.match(main, /RUNNING_IDENTITY/);
assert.match(main, /fetchDeployedIdentity/);

console.log('owner-functional-ui.test: ok');
