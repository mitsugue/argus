#!/usr/bin/env node
'use strict';
const fs = require('fs');
const path = require('path');
const ts = require('typescript');

require.extensions['.ts'] = (module, filename) => {
  const source = fs.readFileSync(filename, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  module._compile(output, filename);
};

const view = require(path.join(__dirname, '..', 'src', 'domain', 'portfolioDecisionView.ts'));
let failed = 0;
function check(name, condition) {
  if (condition) console.log(`  ok  ${name}`);
  else { failed += 1; console.error(`FAIL  ${name}`); }
}

const risk = (symbol, riskLevel, checkNextJa, whyJa = `${symbol} risk`) => ({
  symbol, riskLevel, riskType: 'concentration', checkNextJa, whyJa,
});

const empty = view.buildPortfolioDecisionOverview({
  combinedJpy: null, combinedPlJpy: null, pricedCount: 0, unpriced: [],
  noHoldings: true, top1Symbol: null, top1Pct: null, topThemeJa: null,
  topThemePct: null, jpyPct: null, usdPct: null, risks: [],
});
check('P1 empty holdings has one actionable command',
  empty.command.includes('保有数量') && empty.actionQueue.length === 0);
check('P2 empty holdings is honest about stress',
  empty.stressConditions[0].includes('未算出') && empty.exposure.valueJpy === null);

const populated = view.buildPortfolioDecisionOverview({
  combinedJpy: 12_000_000, combinedPlJpy: -350_000, pricedCount: 7,
  unpriced: ['FUND-X'], noHoldings: false, top1Symbol: '5803', top1Pct: 42,
  topThemeJa: 'AIインフラ', topThemePct: 55, jpyPct: 70, usdPct: 30,
  risks: [
    risk('AAPL', 'medium', 'イベント確認'),
    risk('5803', 'critical', '縮小条件を確認'),
    risk('NVDA', 'high', '集中上限を確認'),
    risk('TSLA', 'low', '価格更新'),
    risk('META', 'medium', '決算確認'),
    risk('8058', 'high', '需給確認'),
    risk('5803', 'high', 'イベント条件も確認'),
  ],
  stressConditions: ['AI調整局面', '円高局面', '金利ショック'],
  nextPortfolioChecks: ['テーマ集中を週次確認'],
});
check('P3 critical risk changes the dominant command',
  populated.command.includes('新規追加を止め'));
check('P4 action queue is severity ordered and capped at five',
  populated.actionQueue.length === 5 && populated.actionQueue[0].symbol === '5803'
  && populated.actionQueue[1].symbol === '8058');
check('P5 exposure keeps priced and unpriced separate',
  populated.exposure.pricedCount === 7 && populated.exposure.unpricedCount === 1);
check('P6 top risks cover concentration, theme, currency and unpriced',
  populated.topRisks.map((item) => item.label).join('|')
    === '銘柄集中|テーマ集中|通貨|未評価');
check('P7 next checks are bounded to two and deduplicated',
  populated.nextChecks.length <= 2 && new Set(populated.nextChecks).size === populated.nextChecks.length);
check('P8 action queue has at most one command per asset',
  populated.actionQueue.filter((item) => item.symbol === '5803').length === 1);
check('P9 stress conditions are explicit, deduplicated and bounded',
  populated.stressConditions.join('|') === 'AI調整局面|円高局面');

const routeSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'routes', 'CorePortfolio.tsx'), 'utf8');
const overviewSource = fs.readFileSync(path.join(__dirname, '..', 'src', 'components',
  'dashboard', 'PortfolioDecisionOverview.tsx'), 'utf8');
check('P10 first viewport starts with the portfolio overview',
  routeSource.indexOf('<PortfolioDecisionOverview') < routeSource.indexOf('<details className="cp-workspace"'));
check('P11 detailed features remain secondary',
  routeSource.includes('Allocation / Risk / Plan / History')
  && routeSource.includes('PortfolioExposureCard')
  && routeSource.includes('WhatIfPanel')
  && routeSource.includes('DecisionQualityCard'));
check('P12 overview exposes the required contracts',
  ['PORTFOLIO COMMAND', 'TOTAL EXPOSURE', 'TOP RISKS', 'ACTION QUEUE',
    'STRESS', 'NEXT PORTFOLIO CHECK'].every((label) => overviewSource.includes(label)));
check('P13 no Today-open dependency remains',
  routeSource.includes('useAssetIntel({ publish: true, assets })')
  && !routeSource.includes('latestScenarios')
  && !routeSource.includes('latestPlans')
  && !routeSource.includes('latestStrategy')
  && !routeSource.includes('Todayを開いた'));
check('P14 asset-level scenario paragraph is not duplicated here',
  !routeSource.includes('{ps.detailJa}'));
check('P15 queue is bounded in implementation',
  fs.readFileSync(path.join(__dirname, '..', 'src', 'domain',
    'portfolioDecisionView.ts'), 'utf8').includes('actionQueue.length === 5'));

if (failed) {
  console.error(`\npositions-risk tests: ${failed} FAILED`);
  process.exit(1);
}
console.log('\npositions-risk tests: all passed');
