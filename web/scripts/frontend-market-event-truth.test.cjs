#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const ts = require('typescript');

require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};

const root = path.join(__dirname, '..');
const command = fs.readFileSync(path.join(root, 'src/routes/CommandCenter.tsx'), 'utf8');
const today = fs.readFileSync(path.join(root, 'src/components/today/ArgusTodayPanel.tsx'), 'utf8');
const notifications = fs.readFileSync(path.join(root, 'src/routes/NotificationsPage.tsx'), 'utf8');
const events = fs.readFileSync(
  path.join(root, 'src/components/dashboard/ImportantEventsCard.tsx'), 'utf8');
const eventCss = fs.readFileSync(
  path.join(root, 'src/components/dashboard/ImportantEventsCard.css'), 'utf8');
const { deriveDashboardEventDisplayState } = require(
  path.join(root, 'src/lib/dashboardEventState.ts'));

let failed = 0;
function check(name, condition) {
  if (condition) console.log(`  ok  ${name}`);
  else { failed += 1; console.error(`FAIL  ${name}`); }
}

check('market score excludes device-local held-card reduction',
  !command.includes('cardGroups.jpWatch') && !command.includes('cardGroups.usWatch'));
check('market score excludes holder risk overlay',
  !command.includes('ownerRisk: overlay.holderRiskOverlay')
  && !command.includes('ownerPolicyLimit:'));
check('canonical event review lives once on Notifications',
  !command.includes('<ImportantEventsCard')
  && notifications.includes('<ImportantEventsCard />')
  && today.includes("onNavigate('notifications')")
  && events.includes('setShowAll') && events.includes('is-expanded')
  && eventCss.includes('.ie-card:not(.is-expanded)'));
check('Today market view does not render portfolio-wide commands',
  !today.includes('保有確認') && !today.includes('新規 <b>')
  && !today.includes('買増 <b>') && !today.includes('保有 <b>'));
check('history coverage is shown without claiming ten years early',
  today.includes('10年未達') && today.includes('projection.sourceHistoryCount'));
check('event detail is organized into before, official and after phases',
  ['発表前', '公式結果', '発表後'].every((label) => events.includes(label))
  && eventCss.includes('.ie-phase-grid'));
check('missing historical prediction remains explicit',
  events.includes('事前予測未保存'));

const notScoreable = deriveDashboardEventDisplayState({
  state: 'not_scoreable',
  officialResult: { available: true },
  caos: { verdict: 'not_scoreable', answerCheckJa: '事前予測なし' },
});
check('not-scoreable released event still shows result and honest answer check',
  notScoreable.released && notScoreable.showActualFirst && notScoreable.showAnswerCheck);

if (failed) {
  console.error(`\nfrontend-market-event-truth: ${failed} failed`);
  process.exit(1);
}
console.log('\nfrontend-market-event-truth: all passed');
