import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (file) => fs.readFileSync(path.join(root, file), 'utf8');

const today = read('src/components/today/ArgusTodayPanel.tsx');
const css = read('src/components/today/ArgusToday.css');
const hook = read('src/hooks/useNewsIntelligence.ts');
const navigation = read('src/navigation.ts');

assert.match(today, /data-event-memory-status/);
assert.match(today, /data-flag-recovery/);
assert.match(today, /data-calibration-mode/);
assert.match(today, /フラグ回収/);
assert.match(today, /独立事例/);
assert.match(today, /根拠不足/);
assert.match(today, /校正 SHADOW · 判断権限なし/);
assert.match(css, /\.at-event-memory/);
assert.match(hook, /calibrationMode:\s*'SHADOW'/);
assert.match(hook, /sdaAuthority:\s*false/);
assert.match(hook, /\/api\/argus\/news-intelligence/);
assert.doesNotMatch(hook, /fetch\([^]*\/api\/argus\/event-memory/);
assert.doesNotMatch(navigation, /event-memory|eventMemory/);

console.log('causal event memory UI contract: PASS');
