// Today のカードの順番と有無(正本: docs/TODAY_CARD_ORDER.md・オーナー承認)。
// 並べ替え・削除・データ有無での非表示はここで失敗する。変更はオーナー承認後に
// 正本とこの検査を同時に更新する。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');
const panel = read('src/components/today/ArgusTodayPanel.tsx');
const order = read('../docs/TODAY_CARD_ORDER.md');

// 正本の番号・目印・許される表示条件(日経平均1321を選んだ日本市場が前提)。
const JP_1321 = "{view.selectedMarket === 'JP' && selectedSymbol === '1321' &&";
const JP_ONLY = '{!usSelected &&';
const ALWAYS = '';
const cards = [
  [1, '今日の見立て', '<section className="at-view-hero"', ALWAYS],
  [2, 'FUTURE MAP', '<FutureMapCard />', JP_1321],
  [3, '日経平均のチャート', '<JapanMarketHorizonComparison />', '&&'],
  [4, '価格の目盛り', '<LevelMapCard />', JP_1321],
  [5, '6サイン', '<article className={`at-decision at-primary-hero', ALWAYS],
  [6, '自分の銘柄への影響', 'aria-label="自分の銘柄への影響"', '{view.holdingsReview.length > 0 && <section className="at-priorities card"'],
  [7, '重大ニュース・市場リスク', '<section id="today-material-news"', ALWAYS],
  [8, 'ニュースの一覧', '<details id="today-news-details"', ALWAYS],
  [9, '重要イベント', '<section id="today-events"', ALWAYS],
  [10, '共通の市場の状況', '<SharedMarketContext', JP_ONLY],
  [11, '信用の動き', '<MarginDynamicsCard', JP_ONLY],
  [12, '円の持ち高', '<JpyPositionCard', JP_ONLY],
  [13, '他の市場を見る', '<details className="at-other-markets card"', ALWAYS],
  [14, '市場データの一覧・従来の判定', '<summary>DATA</summary>', '<details className="at-event card at-context" aria-label="市場観・需給（参考）">'],
];

let previous = -1;
for (const [number, name, marker, guard] of cards) {
  const at = panel.indexOf(marker);
  assert.ok(at >= 0, `${number} ${name}: Today から消えています`);
  assert.equal(panel.indexOf(marker, at + 1), -1, `${number} ${name}: 2回描画されています`);
  assert.ok(at > previous, `${number} ${name}: 正本の順番と違います`);
  previous = at;
  const lineStart = panel.lastIndexOf('\n', at) + 1;
  const prefix = panel.slice(lineStart, at).trim();
  assert.equal(prefix, guard, `${number} ${name}: データの有無で消える条件が付いています(${prefix})`);
  if (number === 3) assert.ok(panel.slice(panel.lastIndexOf('\n', lineStart - 2), lineStart).includes("selectedSymbol === '1321'"), '3 日経平均のチャートの条件');
  // 正本の表に同じ番号・名前の行があること。
  assert.ok(new RegExp(`^\\| ${number} \\| [^\\n]*${name.split('・')[0]}`, 'm').test(order),
    `${number} ${name}: docs/TODAY_CARD_ORDER.md の表と食い違っています`);
}
assert.equal((order.match(/^\| \d+ \|/gm) || []).length, cards.length, '正本の枚数と検査の枚数が違います');

// 見立ての上に独立した公式結果の枠を置かない(2026-10-15 オーナー承認・イベント欄の先頭へ統合)。
assert.ok(!panel.includes('<OfficialMacroResults'), '見立ての上に公式結果の枠があります');

// 見立ての中: 値 → 見立て → タイル → 市場の現在位置 → 材料の向き(today-decision.test.cjs)、
// その後に「見通しを詳しく」と根拠。3か所とも同じ見立ての帯を先頭に使う。
const surface = read('src/components/today/ArgusEditorialSurface.tsx');
const live = surface.slice(surface.indexOf('argus-editorial--live'));
assert.ok(live.indexOf('<TodayDecisionStrip') < live.indexOf('見通しを詳しく')
  && live.indexOf('見通しを詳しく') < live.indexOf('この見通しの根拠・過去の記録'), '最新の版の順番');
const retained = surface.slice(surface.lastIndexOf('<TodayDecisionStrip'));
assert.ok(retained.indexOf('<TodayDecisionStrip') < retained.indexOf('plan.elements.map'), '保存版の順番');
const brief = read('src/components/today/MarketBriefCard.tsx');
assert.ok(brief.indexOf('<TodayDecisionStrip') < brief.indexOf('at-brief__rows'), '従来の表示の順番');
for (const [file, text] of [['ArgusEditorialSurface', surface], ['MarketBriefCard', brief]]) {
  assert.ok(!text.includes('<MarketPositionCard'), `${file}: 市場の現在位置は見立ての帯の中に1回だけ`);
}
const strip = read('src/components/today/TodayDecisionStrip.tsx');
// 2026-10-20 オーナー承認: 見立て → タイル4つ → 市場の現在位置 → 材料ごとの向き。
assert.ok(strip.indexOf('today-strip__verdict') < strip.indexOf('today-strip__tiles')
  && strip.indexOf('today-strip__tiles') < strip.indexOf('<MarketPositionCard')
  && strip.indexOf('<MarketPositionCard') < strip.indexOf('today-strip__rows'), 'タイル4つの下に市場の現在位置');
console.log('Today のカードの順番と有無が正本どおり PASS');
