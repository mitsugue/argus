#!/usr/bin/env node
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

require.extensions['.ts'] = (mod, filename) => {
  const output = ts.transpileModule(fs.readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
    fileName: filename,
  }).outputText;
  mod._compile(output, filename);
};

const root = path.join(__dirname, '..');
const authority = require(path.join(root, 'src', 'domain', 'singleDecisionAuthority.ts'));
const local = require(path.join(root, 'src', 'lib', 'sdaDeviceLocal.ts'));

class MemoryStorage {
  constructor() {
    this.values = new Map();
    this.setCalls = 0;
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.setCalls += 1;
    this.values.set(key, String(value));
  }
}

function exactUtc(epochMs) {
  return new Date(epochMs).toISOString().replace('.000Z', 'Z');
}

function pair(index = 0) {
  const at = exactUtc(Date.parse('2026-08-16T09:00:00Z') + index * 1000);
  const input = authority.buildDataGatedInputV2({
    subject: { kind: 'ASSET', instrumentId: '7203', market: 'JP', horizon: 'FIVE_DAY' },
    decisionAt: at,
    informationCutoffAt: at,
    ownerContext: {
      schemaVersion: 'owner-decision-context-v1',
      privacyClass: 'DEVICE_LOCAL',
      asOf: at,
      positionState: 'NOT_HELD',
      positionRiskBand: 'LOW',
      concentrationBand: 'LOW',
      addPermission: 'ALLOWED',
    },
  });
  const result = authority.evaluateSingleDecisionAuthority(input);
  return { result, adapter: authority.buildPredictionLedgerV2Adapter(result) };
}

function main() {
  assert.deepEqual(local.deriveLocalOwnerRiskBands({
    positionState: 'NOT_HELD', flaggedPositionRisk: null,
    positionRiskKnown: false, concentrationWeightPct: null,
  }), { positionRiskBand: 'LOW', concentrationBand: 'LOW' });
  assert.deepEqual(local.deriveLocalOwnerRiskBands({
    positionState: 'HELD', flaggedPositionRisk: null,
    positionRiskKnown: true, concentrationWeightPct: 8,
  }), { positionRiskBand: 'LOW', concentrationBand: 'LOW' });
  assert.deepEqual(local.deriveLocalOwnerRiskBands({
    positionState: 'HELD', flaggedPositionRisk: null,
    positionRiskKnown: false, concentrationWeightPct: null,
  }), { positionRiskBand: 'UNKNOWN', concentrationBand: 'UNKNOWN' });
  assert.deepEqual(local.deriveLocalOwnerRiskBands({
    positionState: 'UNKNOWN', flaggedPositionRisk: 'critical',
    positionRiskKnown: true, concentrationWeightPct: 50,
  }), { positionRiskBand: 'UNKNOWN', concentrationBand: 'UNKNOWN' });
  assert.deepEqual(local.deriveLocalOwnerRiskBands({
    positionState: 'HELD', flaggedPositionRisk: 'high',
    positionRiskKnown: true, concentrationWeightPct: 28,
  }), { positionRiskBand: 'HIGH', concentrationBand: 'HIGH' });

  const storage = new MemoryStorage();
  assert.deepEqual(local.readDeviceLocalSdaLedger(storage), { status: 'EMPTY', entries: [] });
  const first = pair();
  assert.deepEqual(local.appendDeviceLocalSdaLedger(first.result, first.adapter, storage), {
    status: 'APPENDED', entryCount: 1, evictedCount: 0,
  });
  const writesAfterAppend = storage.setCalls;
  assert.deepEqual(local.appendDeviceLocalSdaLedger(first.result, first.adapter, storage), {
    status: 'DUPLICATE', entryCount: 1, evictedCount: 0,
  });
  assert.equal(storage.setCalls, writesAfterAppend, 'duplicate adapter IDs must not rewrite storage');

  const read = local.readDeviceLocalSdaLedger(storage);
  assert.equal(read.status, 'OK');
  assert.equal(read.entries.length, 1);
  assert.equal(read.entries[0].adapterId, first.adapter.adapterId);
  assert.equal(local.verifyDeviceLocalSdaLedgerEntry(read.entries[0]), true);
  const storedText = storage.getItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY);
  const storedDocument = JSON.parse(storedText);
  assert.equal(local.verifyDeviceLocalSdaLedgerDocument(storedDocument), true);
  for (const key of ['quantity', 'avgCost', 'costBasis', 'pnl', 'pnlPct',
    'pl', 'plPct', 'ownerContext', 'positionState', 'positionRiskBand',
    'concentrationBand', 'addPermission', 'privateRaw']) {
    assert.equal(storedText.includes(`"${key}"`), false, `${key} leaked into the local ledger`);
  }

  const privateResult = { ...first.result, quantity: 123, avgCost: 456 };
  assert.equal(local.appendDeviceLocalSdaLedger(
    privateResult, first.adapter, storage).status, 'INVALID_RECORD');
  const privateAdapter = { ...first.adapter, privateRaw: { pnl: 99 } };
  assert.equal(local.appendDeviceLocalSdaLedger(
    first.result, privateAdapter, storage).status, 'INVALID_RECORD');
  assert.equal(storage.getItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY), storedText,
    'rejected private records must not mutate the ledger');

  const tamperedStorage = new MemoryStorage();
  const tampered = JSON.parse(storedText);
  tampered.entries[0].adapter.primaryAction = 'EXIT';
  tamperedStorage.setItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY, JSON.stringify(tampered));
  assert.equal(local.verifyDeviceLocalSdaLedgerDocument(tampered), false);
  assert.equal(local.readDeviceLocalSdaLedger(tamperedStorage).status, 'CORRUPT');
  assert.equal(local.appendDeviceLocalSdaLedger(
    pair(1).result, pair(1).adapter, tamperedStorage).status, 'CORRUPT');

  const corruptStorage = new MemoryStorage();
  corruptStorage.setItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY, '{broken');
  const corruptBefore = corruptStorage.getItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY);
  assert.equal(local.appendDeviceLocalSdaLedger(
    first.result, first.adapter, corruptStorage).status, 'CORRUPT');
  assert.equal(corruptStorage.getItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY), corruptBefore,
    'a corrupt append-only ledger must never be overwritten');

  const failingRead = { getItem() { throw new Error('denied'); }, setItem() {} };
  assert.equal(local.readDeviceLocalSdaLedger(failingRead).status, 'STORAGE_UNAVAILABLE');
  const failingWrite = { getItem() { return null; }, setItem() { throw new Error('quota'); } };
  assert.equal(local.appendDeviceLocalSdaLedger(
    first.result, first.adapter, failingWrite).status, 'STORAGE_UNAVAILABLE');

  const bounded = new MemoryStorage();
  const generated = [];
  for (let index = 0; index < local.MAX_DEVICE_LOCAL_SDA_ENTRIES + 5; index += 1) {
    const next = pair(index);
    generated.push(next);
    assert.equal(local.appendDeviceLocalSdaLedger(
      next.result, next.adapter, bounded).status, 'APPENDED');
  }
  const boundedRead = local.readDeviceLocalSdaLedger(bounded);
  assert.equal(boundedRead.status, 'OK');
  assert.ok(boundedRead.entries.length <= local.MAX_DEVICE_LOCAL_SDA_ENTRIES);
  assert.equal(boundedRead.entries.some((row) =>
    row.adapterId === generated.at(-1).adapter.adapterId), true);
  assert.equal(boundedRead.entries.some((row) =>
    row.adapterId === generated[0].adapter.adapterId), false,
  'bounded-tail retention must evict the oldest row without mutating retained rows');
  assert.ok(Buffer.byteLength(
    bounded.getItem(local.DEVICE_LOCAL_SDA_LEDGER_KEY), 'utf8')
    <= local.MAX_DEVICE_LOCAL_SDA_LEDGER_BYTES);

  const helperSource = fs.readFileSync(
    path.join(root, 'src', 'lib', 'sdaDeviceLocal.ts'), 'utf8');
  const hookSource = fs.readFileSync(
    path.join(root, 'src', 'hooks', 'useAssetIntel.ts'), 'utf8');
  const backupSource = fs.readFileSync(
    path.join(root, 'src', 'lib', 'backup.ts'), 'utf8');
  assert.doesNotMatch(helperSource, /fetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon/);
  // v13.5.13 (owner decision, spec §19): issued decisions must survive device
  // loss, so the ledger rides the ENCRYPTED vault. The entry privacy screen
  // (FORBIDDEN_PRIVATE_KEYS) still keeps quantity/cost/P&L out of every row.
  assert.equal(backupSource.includes(local.DEVICE_LOCAL_SDA_LEDGER_KEY), true,
    'device-local SDA ledger must ride the encrypted vault backup allowlist');
  assert.match(hookSource, /appendDeviceLocalSdaLedger\(result, adapter\)/);
  assert.match(hookSource, /deriveLocalOwnerRiskBands/);

  console.log('device-local-sda-ledger.test: ok');
}

main();
