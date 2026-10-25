// 2026-10-20 (owner decision): an unvalidated median path is not drawn; past analogues stay as references.
const fs = require('node:fs'), assert = require('node:assert/strict');
const source = fs.readFileSync('src/components/chart/JapanMarketComparisonChart.tsx', 'utf8');
assert.ok(source.includes("const forecast = validated ? document.forecast.line : [];"), 'line only when validated');
assert.ok(source.includes("const band = validated ? document.forecast.band : [];"), 'band only when validated');
assert.ok(source.includes('data-forecast-role="references-only"'), 'the reason is stated');
assert.ok(source.includes('予想の線なし'), 'says no line is drawn');
assert.ok(source.includes('data-series="past-subsequent-reference"'), 'what followed each analogue stays');
assert.ok(!source.includes("'参考経路（中央値）'"), 'no legend entry for an undrawn line');
// The FUTURE MAP chart is not touched by this change.
const futureMap = fs.readFileSync('src/components/chart/NikkeiResearchChart.tsx', 'utf8');
assert.ok(!futureMap.includes('references-only'));
console.log('comparison references only: ok');
