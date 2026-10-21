// 2026-10-21 オーナー指示: Today の各ブロックの見出しを、FUTURE MAP のように白く・少し大きく、
// 見出しとわかる同じ形(左の水色の帯)にそろえる。どのカードの見出しも共通の規則に入っていることを確かめる。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const css = fs.readFileSync(path.join(root, 'src/components/today/ReadingHierarchy.css'), 'utf8');
const start = css.indexOf('/* 2026-10-21 owner request');
assert.ok(start >= 0, '共通の見出しの規則がありません');
const rule = css.slice(start, css.indexOf('}', start) + 1);
for (const selector of ['.fm-head > b', '#today-nikkei-chart > h3', '.lm-heading > b', '.at-seven > summary > small',
  '.at-priorities .at-head > b', '#today-material-news .at-head > b', '#today-events > .at-head > b', '#today-news-details > summary',
  '.sector-heatmap > h3', '.at-internals > h3', '.at-margin-dynamics > h3', '.at-other-markets > summary', '.at-context > summary',
  '.argus-editorial__edition > span:first-child']) {
  assert.ok(rule.includes(selector), `見出しが共通の形に入っていません: ${selector}`);
}
for (const value of ['color: var(--text-main)', 'font-size: 17px', 'font-weight: 700', 'border-left: 3px solid var(--cyan)']) {
  assert.ok(rule.includes(value), `共通の見出しの値が違います: ${value}`);
}
// 共通の規則が最後に読まれる(カードごとの薄い色・小さい字に負けない)。
const panel = fs.readFileSync(path.join(root, 'src/components/today/ArgusTodayPanel.tsx'), 'utf8');
assert.ok(panel.indexOf("import './ReadingHierarchy.css'") > panel.indexOf("import './ArgusToday.css'"), '読み込みの順番');
console.log('Today の各ブロックの見出しが共通の形 PASS');
