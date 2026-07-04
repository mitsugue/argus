// V11.9.0 — Portfolio Sync / Snapshot Foundation (device-local core).
//
// THREE LAYERS (mirrors argus_portfolio_sync.py, the schema source of truth):
//   A. Local: localStorage (argus.assets.v1 etc.) — unchanged, offline-first.
//   B. Private cloud: the EXISTING passphrase vault (lib/vault.ts) — the device
//      encrypts, only ciphertext reaches the cloud, any device with the
//      passphrase restores/merges. That IS today's Mac/iPhone/iPad sync path.
//      A server-side PLAINTEXT store stays disabled until real auth exists.
//   C. Snapshot/audit (new): append-only local snapshots + decision-audit
//      records under the keys below. Both are listed in BACKUP_KEYS, so they
//      ride the encrypted vault → preserved permanently AND synced, while the
//      cloud still only ever sees ciphertext.
//
// No broker login, no trading, no fabricated values: a snapshot records only
// what the engines actually computed at that moment.

import type { AssetItem } from '../types/assetItem';
import type { PortfolioExposure } from '../domain/positionExposure';

export const SYNC_SCHEMA_VERSION = 'portfolio-sync-v1';
export const SNAPSHOT_SCHEMA_VERSION = 'portfolio-snapshot-v1';
export const AUDIT_SCHEMA_VERSION = 'decision-audit-v1';

export const SNAPSHOTS_KEY = 'argus.portfolio.snapshots.v1';
export const AUDIT_KEY = 'argus.decision.audit.v1';
export const SYNC_META_KEY = 'argus.portfolioSync.meta.v1';
const SNAPSHOT_CAP = 60;      // ~2 months of dailies in localStorage
const AUDIT_CAP = 800;

// ── models ──────────────────────────────────────────────────────────────────

export interface PortfolioSnapshot {
  schemaVersion: typeof SNAPSHOT_SCHEMA_VERSION;
  snapshotId: string;
  portfolioId: string;
  asOf: string;                 // date (JST day) this snapshot represents
  createdAt: string;
  positionsSummary: { symbol: string; held: boolean; pnlPct: number | null; weightPct: number | null; themeJa: string }[];
  exposureSummary: { byTheme: { ja: string; pct: number }[]; jpyPct: number | null; usdPct: number | null;
    top1Symbol: string | null; top1Pct: number | null; singleNameRisk: string | null };
  riskSignalsSummary: { symbol: string; riskLevel: string; riskType: string; whyJa: string }[];
  marketRegimeSummary: { summaryJa: string; headwinds: string[]; tailwinds: string[] };
  institutionalSummary: null;   // not captured locally yet — honest null
  flowSummary: { symbol: string; flowClass: string }[];
  eventSummary: string[];
  actionReadinessSummary: { symbol: string; readiness: string }[];
  /** v11.10.0: 需給ランク当時値 — 後日「A/Bは続伸したか」「D/E警告は正しかったか」の答え合わせ用 */
  supplyDemandSummary: { symbol: string; rank: string; condition: string }[];
  squeezeProne: string[];
  creditOverhang: string[];
  pricesUsed: Record<string, number>;
  staleDataFlags: string[];
  missingEvidence: string[];
  appVersion: string;
  engineVersions: { positionExposure: string; sync: string };
  integrityHash: string;
  privacyLevel: 'local_only';
}

export interface DecisionAuditRecord {
  schemaVersion: typeof AUDIT_SCHEMA_VERSION;
  id: string;
  asOf: string;
  symbol: string;
  market: string;
  decisionContext: string;      // = add-more readiness at the time
  ownerAction: null;            // owner can annotate later (bought/held/…)
  reasonCodes: string[];
  flowClass: string | null;
  positionRisk: string | null;
  marketRegime: string | null;
  priceAtDecision: number | null;
  futureReturn1d: null; futureReturn3d: null; futureReturn5d: null; futureReturn20d: null;
  reviewNote: null;
  privacyLevel: 'local_only';
}

export interface PortfolioBackupFile {
  app: 'argus';
  kind: 'portfolio-backup';
  schemaVersion: typeof SYNC_SCHEMA_VERSION;
  exportedAt: string;
  appVersion: string;
  positions: { symbol: string; market: string; name: string; quantity: number | null;
    avgCost: number | null; memo?: string; assetType: string }[];
  snapshots: PortfolioSnapshot[];
  decisionAudit: DecisionAuditRecord[];
}

interface SyncMeta { lastExportAt?: string; lastImportAt?: string; lastSnapshotAt?: string; lastSnapshotDay?: string; }

// ── storage helpers (never throw) ───────────────────────────────────────────

function readJson<T>(key: string, fallback: T): T {
  try { const raw = localStorage.getItem(key); return raw ? (JSON.parse(raw) as T) : fallback; }
  catch { return fallback; }
}
function writeJson(key: string, v: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* quota — keep app alive */ }
}
export function syncMeta(): SyncMeta { return readJson<SyncMeta>(SYNC_META_KEY, {}); }
function patchMeta(p: Partial<SyncMeta>): void { writeJson(SYNC_META_KEY, { ...syncMeta(), ...p }); }

export function listSnapshots(): PortfolioSnapshot[] { return readJson<PortfolioSnapshot[]>(SNAPSHOTS_KEY, []); }
export function listAudit(): DecisionAuditRecord[] { return readJson<DecisionAuditRecord[]>(AUDIT_KEY, []); }

function djb2(s: string): string {
  let h = 5381;
  for (let i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) >>> 0;
  return h.toString(16);
}
const jstDay = (): string =>
  new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);

// ── snapshot / audit creation ───────────────────────────────────────────────

export function createSnapshot(
  pe: PortfolioExposure,
  opts: { appVersion: string; flowBySymbol?: Record<string, string>; events?: string[];
    supplyDemand?: { symbol: string; rank: string; condition: string }[] },
): PortfolioSnapshot | null {
  // Never fabricate: without any priced holding there is nothing to snapshot —
  // watchlist-only state is not portfolio history.
  if (pe.noHoldings || pe.base.holdings.length === 0) return null;
  const now = new Date().toISOString();
  const prices: Record<string, number> = {};
  for (const h of pe.base.holdings) prices[h.symbol.toUpperCase()] = h.price;
  const flow = opts.flowBySymbol ?? {};
  const body: Omit<PortfolioSnapshot, 'integrityHash'> = {
    schemaVersion: SNAPSHOT_SCHEMA_VERSION,
    snapshotId: `snap-${jstDay()}-${djb2(now)}`,
    portfolioId: 'default',
    asOf: jstDay(),
    createdAt: now,
    positionsSummary: Object.values(pe.notes).filter((n) => n.held)
      .map((n) => ({ symbol: n.symbol, held: true, pnlPct: n.pnlPct ?? null,
        weightPct: n.weightPct ?? null, themeJa: n.themeJa })),
    exposureSummary: {
      byTheme: pe.byTheme.map((t) => ({ ja: t.ja, pct: Math.round(t.pct * 10) / 10 })),
      jpyPct: pe.jpyPct, usdPct: pe.usdPct,
      top1Symbol: pe.top1Symbol, top1Pct: pe.top1Pct, singleNameRisk: pe.singleNameRisk,
    },
    riskSignalsSummary: pe.risks.map((r) => ({ symbol: r.symbol, riskLevel: r.riskLevel,
      riskType: r.riskType, whyJa: r.whyJa })),
    marketRegimeSummary: { summaryJa: pe.regimeSummaryJa, headwinds: pe.headwinds, tailwinds: pe.tailwinds },
    institutionalSummary: null,
    flowSummary: Object.entries(flow).map(([symbol, flowClass]) => ({ symbol, flowClass })),
    eventSummary: opts.events ?? [],
    actionReadinessSummary: Object.values(pe.notes).map((n) => ({ symbol: n.symbol, readiness: n.readiness })),
    supplyDemandSummary: (opts.supplyDemand ?? []).slice(0, 10),
    squeezeProne: (opts.supplyDemand ?? []).filter((x) => x.condition === 'squeeze_prone').map((x) => x.symbol),
    creditOverhang: (opts.supplyDemand ?? []).filter((x) => x.condition === 'credit_overhang').map((x) => x.symbol),
    pricesUsed: prices,
    staleDataFlags: pe.unpriced,
    missingEvidence: [
      ...(pe.unpriced.length ? [`価格未取得: ${pe.unpriced.join('/')}`] : []),
      '機関シグナル要約は未収録(将来対応)',
    ],
    appVersion: opts.appVersion,
    engineVersions: { positionExposure: 'position-exposure-v1', sync: SYNC_SCHEMA_VERSION },
    privacyLevel: 'local_only',
  };
  const snap: PortfolioSnapshot = { ...body, integrityHash: djb2(JSON.stringify(body)) };
  const all = [snap, ...listSnapshots().filter((s) => s.asOf !== snap.asOf)].slice(0, SNAPSHOT_CAP);
  writeJson(SNAPSHOTS_KEY, all);
  patchMeta({ lastSnapshotAt: now, lastSnapshotDay: snap.asOf });
  appendAudit(pe, snap, flow);
  return snap;
}

function appendAudit(pe: PortfolioExposure, snap: PortfolioSnapshot,
                     flow: Record<string, string>): void {
  const riskBySym = new Map(pe.risks.map((r) => [r.symbol, r.riskLevel]));
  const recs: DecisionAuditRecord[] = Object.values(pe.notes).map((n) => ({
    schemaVersion: AUDIT_SCHEMA_VERSION,
    id: `da-${snap.asOf}-${n.symbol}`,
    asOf: snap.createdAt,
    symbol: n.symbol,
    market: /^\d/.test(n.symbol) ? 'JP' : 'US/OTHER',
    decisionContext: n.readiness,
    ownerAction: null,
    reasonCodes: [n.whyJa.slice(0, 60)],
    flowClass: flow[n.symbol] ?? null,
    positionRisk: riskBySym.get(n.symbol) ?? null,
    marketRegime: pe.regimeSummaryJa.slice(0, 60) || null,
    priceAtDecision: snap.pricesUsed[n.symbol] ?? null,
    futureReturn1d: null, futureReturn3d: null, futureReturn5d: null, futureReturn20d: null,
    reviewNote: null,
    privacyLevel: 'local_only',
  }));
  const existing = listAudit().filter((r) => !r.id.startsWith(`da-${snap.asOf}-`));
  writeJson(AUDIT_KEY, [...recs, ...existing].slice(0, AUDIT_CAP));
}

/** Auto daily snapshot (called once per app open when data is ready). */
export function maybeDailySnapshot(pe: PortfolioExposure, appVersion: string,
                                   flowBySymbol?: Record<string, string>,
                                   supplyDemand?: { symbol: string; rank: string; condition: string }[]): boolean {
  if (syncMeta().lastSnapshotDay === jstDay()) return false;
  return createSnapshot(pe, { appVersion, flowBySymbol, supplyDemand }) != null;
}

// ── export / import ─────────────────────────────────────────────────────────

export function buildPortfolioBackup(assets: AssetItem[], appVersion: string): PortfolioBackupFile {
  return {
    app: 'argus', kind: 'portfolio-backup',
    schemaVersion: SYNC_SCHEMA_VERSION,
    exportedAt: new Date().toISOString(),
    appVersion,
    positions: assets.map((a) => ({ symbol: a.symbol, market: a.market,
      name: a.displayNameJa || a.displayName, quantity: a.quantity ?? null,
      avgCost: a.avgCost ?? null, memo: a.memo, assetType: a.assetType })),
    snapshots: listSnapshots(),
    decisionAudit: listAudit(),
  };
}

export function downloadPortfolioBackup(assets: AssetItem[], appVersion: string): void {
  const file = buildPortfolioBackup(assets, appVersion);
  const blob = new Blob([JSON.stringify(file, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `argus-portfolio-${jstDay()}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  patchMeta({ lastExportAt: new Date().toISOString() });
}

export interface ImportPreview {
  ok: boolean;
  errorJa?: string;
  file?: PortfolioBackupFile;
  withQuantity: number;
  watchOnly: number;
  snapshots: number;
  symbols: string[];
}

/** Validate WITHOUT applying — the UI shows this preview + merge/replace choice.
 *  Never executes file content; JSON.parse only. */
export function previewImport(text: string): ImportPreview {
  let parsed: unknown;
  try { parsed = JSON.parse(text); }
  catch { return { ok: false, errorJa: 'JSONとして読めませんでした。', withQuantity: 0, watchOnly: 0, snapshots: 0, symbols: [] }; }
  const f = parsed as Partial<PortfolioBackupFile>;
  if (f?.app !== 'argus' || f?.kind !== 'portfolio-backup' || !Array.isArray(f?.positions)) {
    return { ok: false, errorJa: 'ARGUSのポートフォリオバックアップ形式ではありません。', withQuantity: 0, watchOnly: 0, snapshots: 0, symbols: [] };
  }
  if (f.schemaVersion !== SYNC_SCHEMA_VERSION) {
    return { ok: false, errorJa: `スキーマ版数が未対応です(${String(f.schemaVersion)})。`, withQuantity: 0, watchOnly: 0, snapshots: 0, symbols: [] };
  }
  const bad = f.positions.some((p) => !p || typeof p.symbol !== 'string'
    || (p.quantity != null && typeof p.quantity !== 'number')
    || (p.avgCost != null && typeof p.avgCost !== 'number'));
  if (bad) return { ok: false, errorJa: 'positionsの形式が壊れています。', withQuantity: 0, watchOnly: 0, snapshots: 0, symbols: [] };
  const withQ = f.positions.filter((p) => (p.quantity ?? 0) > 0);
  return {
    ok: true, file: f as PortfolioBackupFile,
    withQuantity: withQ.length,
    watchOnly: f.positions.length - withQ.length,
    snapshots: Array.isArray(f.snapshots) ? f.snapshots.length : 0,
    symbols: withQ.slice(0, 8).map((p) => p.symbol),
  };
}

export interface ApplyResult { updated: number; added: number; snapshotsMerged: number; }

/** Apply a previewed import. merge = fill/update only symbols in the file;
 *  replace = same but also CLEARS quantity on assets NOT in the file (deleting
 *  assets themselves is never done). Snapshots merge by asOf (no dupes). */
export function applyImport(
  file: PortfolioBackupFile,
  assets: AssetItem[],
  mode: 'merge' | 'replace',
  ops: {
    updateHolding: (id: string, h: { quantity?: number | null; avgCost?: number | null }) => void;
    add: (a: { market: string; assetType: string; source: string; symbol: string;
      displayName: string; displayNameJa?: string; memo?: string }) => string | null;
  },
): ApplyResult {
  const bySym = new Map(assets.map((a) => [`${a.market}:${a.symbol.toUpperCase()}`, a]));
  let updated = 0, added = 0;
  const inFile = new Set<string>();
  for (const p of file.positions) {
    const key = `${p.market}:${p.symbol.toUpperCase()}`;
    inFile.add(key);
    const existing = bySym.get(key);
    if (existing) {
      if (p.quantity != null || p.avgCost != null) {
        ops.updateHolding(existing.id, { quantity: p.quantity, avgCost: p.avgCost });
        updated++;
      }
    } else if ((p.quantity ?? 0) > 0) {
      const id = ops.add({ market: p.market, assetType: p.assetType || 'jp_equity',
        source: 'manual', symbol: p.symbol, displayName: p.name || p.symbol, memo: p.memo });
      if (id) { ops.updateHolding(id, { quantity: p.quantity, avgCost: p.avgCost }); added++; }
    }
  }
  if (mode === 'replace') {
    for (const a of assets) {
      const key = `${a.market}:${a.symbol.toUpperCase()}`;
      if (!inFile.has(key) && (a.quantity ?? 0) > 0) {
        ops.updateHolding(a.id, { quantity: null, avgCost: null });
      }
    }
  }
  // snapshots: merge by asOf, keep newest-first, capped
  const have = new Set(listSnapshots().map((s) => s.asOf));
  const incoming = (file.snapshots ?? []).filter((s) => s?.asOf && !have.has(s.asOf));
  if (incoming.length) {
    writeJson(SNAPSHOTS_KEY, [...incoming, ...listSnapshots()]
      .sort((a, b) => (a.asOf < b.asOf ? 1 : -1)).slice(0, SNAPSHOT_CAP));
  }
  patchMeta({ lastImportAt: new Date().toISOString() });
  return { updated, added, snapshotsMerged: incoming.length };
}

// ── private-cloud adapter (interface now; enabled later) ────────────────────

export interface CloudSyncStatus {
  mode: 'disabled' | 'client_encrypted_vault' | 'private_backend';
  noteJa: string;
}
export interface PortfolioCloudAdapter {
  getSyncStatus(): Promise<CloudSyncStatus>;
  pullPortfolio(): Promise<{ status: 'disabled' } | { status: 'ok'; positions: unknown[] }>;
  pushPortfolio(): Promise<{ status: 'disabled' | 'ok' }>;
  listSnapshots(): Promise<{ status: 'disabled' } | { status: 'ok'; snapshots: PortfolioSnapshot[] }>;
  createSnapshot(): Promise<{ status: 'disabled' | 'ok' }>;
  restoreSnapshot(id: string): Promise<{ status: 'disabled' | 'ok' }>;
}

/** The only adapter today: server-side plaintext sync is intentionally off.
 *  Cross-device sync happens via the client-encrypted vault (lib/vault.ts). */
export const disabledCloudAdapter: PortfolioCloudAdapter = {
  async getSyncStatus() {
    return { mode: 'disabled',
      noteJa: 'クラウド同期(平文)は安全な認証が整うまで無効です。端末間同期は暗号化バックアップ(パスフレーズ)をご利用ください。' };
  },
  async pullPortfolio() { return { status: 'disabled' as const }; },
  async pushPortfolio() { return { status: 'disabled' as const }; },
  async listSnapshots() { return { status: 'disabled' as const }; },
  async createSnapshot() { return { status: 'disabled' as const }; },
  async restoreSnapshot() { return { status: 'disabled' as const }; },
};

/** Handoff / AI Review Sheet — one honest line about where the data lives. */
export function backupStatusTextJa(): string {
  const m = syncMeta();
  const vaultOn = !!localStorage.getItem('argus.vaultPass.v1');
  const parts = [
    vaultOn ? '保有データ: 端末内+パスフレーズ暗号化バックアップで端末間同期中'
            : '保有データ: この端末内のみ(暗号化バックアップ未設定 — バックアップ推奨)',
    m.lastSnapshotAt ? `最終スナップショット: ${m.lastSnapshotAt.slice(0, 16).replace('T', ' ')}` : 'スナップショット未作成',
  ];
  if (!m.lastExportAt) parts.push('エクスポート未実施');
  return parts.join(' / ');
}
