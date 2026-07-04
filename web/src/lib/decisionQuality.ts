// V11.11.0 — Decision Quality / Backtest Foundation (device-local).
// ARGUSの過去ラベルが「その後どうなったか」を端末内で検証する。
// TS port of argus_decision_quality.py (the schema/rules source of truth).
//
// HARD RULES: records/outcomes never leave the device (encrypted vault only);
// prices come from the public cached price-history endpoint; missing history →
// insufficient_price_data (never fabricated); early results are never presented
// as proven performance; owner actions are optional annotations, never inferred.

import { AUDIT_KEY, listAudit, type DecisionAuditRecord } from './portfolioSync';

export interface DecisionOutcome {
  outcomeReturn1d: number | null; outcomeReturn3d: number | null;
  outcomeReturn5d: number | null; outcomeReturn20d: number | null;
  maxDrawdown5d: number | null; maxRunup5d: number | null;
  outcomeStatus: 'pending' | 'partial' | 'complete' | 'insufficient_price_data' | 'unknown';
  outcomeInterpretation: 'supported' | 'contradicted' | 'mixed' | 'inconclusive' | 'not_applicable' | null;
  outcomeReadableJa: string | null;
  updatedAt: string;
}

/** v11.11.0 extension of the stored audit record (outcome + annotation only —
 *  evidence fields stay immutable). */
export type DQRecord = DecisionAuditRecord & {
  outcome?: DecisionOutcome;
  ownerAction?: string | null;
  ownerActionNote?: string | null;
  ownerActionAt?: string | null;
  /** v11.11.0 evidence extras (written at creation only) */
  supplyDemandRank?: string | null;
  supplyDemandCondition?: string | null;
};

const DQ_META_KEY = 'argus.decisionQuality.meta.v1';

function readMeta(): { lastOutcomeUpdateAt?: string } {
  try { return JSON.parse(localStorage.getItem(DQ_META_KEY) || '{}'); } catch { return {}; }
}
function writeMeta(m: { lastOutcomeUpdateAt?: string }): void {
  try { localStorage.setItem(DQ_META_KEY, JSON.stringify(m)); } catch { /* quota */ }
}
function saveAll(recs: DQRecord[]): void {
  try { localStorage.setItem(AUDIT_KEY, JSON.stringify(recs)); } catch { /* quota */ }
}
export function listDQ(): DQRecord[] { return listAudit() as DQRecord[]; }
export function lastOutcomeUpdateAt(): string | null { return readMeta().lastOutcomeUpdateAt ?? null; }

// ── outcome math (port of compute_outcome; trading-day series) ──────────────

export function computeOutcome(basePrice: number | null, baseDate: string,
  datesNewestFirst: string[], closesNewestFirst: number[], now: string): DecisionOutcome {
  const out: DecisionOutcome = {
    outcomeReturn1d: null, outcomeReturn3d: null, outcomeReturn5d: null, outcomeReturn20d: null,
    maxDrawdown5d: null, maxRunup5d: null,
    outcomeStatus: 'pending', outcomeInterpretation: null, outcomeReadableJa: null, updatedAt: now,
  };
  if (!basePrice || basePrice <= 0) { out.outcomeStatus = 'unknown'; return out; }
  if (!datesNewestFirst.length) { out.outcomeStatus = 'insufficient_price_data'; return out; }
  const series = datesNewestFirst.map((d, i) => [d, closesNewestFirst[i]] as const)
    .filter(([d, c]) => d && Number.isFinite(c)).sort((a, b) => (a[0] < b[0] ? -1 : 1));
  const fwd = series.filter(([d]) => d > baseDate);
  if (!fwd.length) {
    out.outcomeStatus = baseDate >= (series[series.length - 1]?.[0] ?? '') ? 'pending' : 'insufficient_price_data';
    return out;
  }
  const ret = (px: number) => Math.round((px - basePrice) / basePrice * 10000) / 100;
  const win = (n: number) => (fwd.length >= n ? fwd[n - 1][1] : null);
  const p1 = win(1), p3 = win(3), p5 = win(5), p20 = win(20);
  out.outcomeReturn1d = p1 != null ? ret(p1) : null;
  out.outcomeReturn3d = p3 != null ? ret(p3) : null;
  out.outcomeReturn5d = p5 != null ? ret(p5) : null;
  out.outcomeReturn20d = p20 != null ? ret(p20) : null;
  const w5 = fwd.slice(0, 5).map(([, c]) => c);
  if (w5.length) {
    out.maxDrawdown5d = ret(Math.min(...w5));
    out.maxRunup5d = ret(Math.max(...w5));
  }
  const filled = [p1, p3, p5, p20].filter((x) => x != null).length;
  out.outcomeStatus = filled === 4 ? 'complete' : filled ? 'partial' : 'pending';
  return out;
}

// ── interpretation (cautious; port of interpret()) ──────────────────────────

export function interpretOutcome(rec: DQRecord, o: DecisionOutcome):
  { interpretation: NonNullable<DecisionOutcome['outcomeInterpretation']>; ja: string } {
  const r5x = o.outcomeReturn5d ?? o.outcomeReturn3d;
  const dd5 = o.maxDrawdown5d, ru5 = o.maxRunup5d;
  const ctx = rec.decisionContext;
  const sdRank = rec.supplyDemandRank ?? '';
  const sdCond = rec.supplyDemandCondition ?? '';
  const flow = rec.flowClass ?? '';
  if (o.outcomeReturn3d == null && o.outcomeReturn5d == null) {
    return { interpretation: 'inconclusive', ja: 'データ不足で判定保留です' };
  }
  if (ctx === 'avoid_chase') {
    if ((dd5 != null && dd5 <= -3) || (r5x != null && r5x <= -1)) {
      return { interpretation: 'supported', ja: '追いかけ買いを避けた後に押しが来ており、この判断は今のところ支持されています。' };
    }
    if (r5x != null && r5x >= 5 && (dd5 == null || dd5 > -2)) {
      return { interpretation: 'contradicted', ja: '押し目なくそのまま上昇が続いたため、この判断は外れた可能性があります。' };
    }
    return { interpretation: 'mixed', ja: '大きな押しも急伸もなく、判定は中間です。' };
  }
  if (ctx === 'add_only_on_pullback') {
    if (dd5 != null && dd5 <= -2) return { interpretation: 'supported', ja: '実際に押し目が発生しており、この判断は今のところ支持されています。' };
    if (r5x != null && r5x >= 5 && (dd5 == null || dd5 > -1.5)) {
      return { interpretation: 'contradicted', ja: '押し目が来ないまま上昇が続き、機会を逃した可能性があります。' };
    }
    return { interpretation: 'mixed', ja: '浅い押しにとどまり、一長一短の結果です。' };
  }
  if (['S', 'A', 'B'].includes(sdRank) && ['monitor', 'hold', 'add_allowed_small'].includes(ctx)) {
    if (sdCond === 'squeeze_prone' || flow === 'short_covering') {
      if (ru5 != null && ru5 >= 3 && r5x != null && r5x < ru5 - 2) {
        return { interpretation: 'supported', ja: '踏み上げ型どおり急伸後に失速しており、買い戻し主導の読みと整合的です。' };
      }
      if (o.outcomeReturn20d != null && o.outcomeReturn20d >= 8) {
        return { interpretation: 'contradicted', ja: '失速せず上昇が継続しており、買い戻し以外の買いが入っていた可能性があります。' };
      }
      return { interpretation: 'mixed', ja: '踏み上げと実需買いの両方が混在した可能性があります。' };
    }
    if (r5x != null && r5x >= 2) return { interpretation: 'supported', ja: '需給良好の読みどおり続伸しており、この判断は今のところ支持されています。' };
    if (r5x != null && r5x <= -3) return { interpretation: 'contradicted', ja: '需給良好にもかかわらず下落しており、この判断は外れた可能性があります。' };
    return { interpretation: 'mixed', ja: '需給良好の後の値動きは中立で、判定は中間です。' };
  }
  if (['D', 'E'].includes(sdRank) && ['wait', 'caution', 'avoid_chase', 'monitor', 'trim_consideration'].includes(ctx)) {
    if ((r5x != null && r5x <= -2) || (ru5 != null && ru5 < 2)) {
      return { interpretation: 'supported', ja: '需給が重い読みどおり戻りが弱く、この判断は今のところ支持されています。' };
    }
    if (r5x != null && r5x >= 5) return { interpretation: 'contradicted', ja: '需給の重さを突き抜けて上昇しており、この判断は外れた可能性があります。' };
    return { interpretation: 'mixed', ja: '需給の重さと値動きが拮抗しており、判定は中間です。' };
  }
  if (['caution', 'wait', 'investigate', 'trim_consideration'].includes(ctx)) {
    if (r5x != null && r5x <= -2) return { interpretation: 'supported', ja: '警戒どおり弱い値動きとなり、この判断は今のところ支持されています。' };
    if (r5x != null && r5x >= 5) return { interpretation: 'contradicted', ja: '警戒に反して強い上昇となりました。' };
    return { interpretation: 'mixed', ja: '警戒後の値動きは中立で、判定は中間です。' };
  }
  return { interpretation: 'not_applicable', ja: 'この種のラベルは成否判定の対象外です' };
}

// ── outcome updater (device-local; throttled to once per JST day) ───────────

const jstDay = (): string => new Date(Date.now() + 9 * 3600_000).toISOString().slice(0, 10);

export async function maybeUpdateOutcomes(backend: string): Promise<number> {
  const meta = readMeta();
  if ((meta.lastOutcomeUpdateAt ?? '').slice(0, 10) === jstDay()) return 0;
  const recs = listDQ();
  const targets = recs.filter((r) =>
    (!r.outcome || (r.outcome.outcomeStatus !== 'complete'
      && r.outcome.outcomeStatus !== 'insufficient_price_data'))
    && r.priceAtDecision != null && r.asOf.slice(0, 10) < jstDay());
  if (!targets.length) { writeMeta({ lastOutcomeUpdateAt: new Date().toISOString() }); return 0; }
  const base = backend.replace(/\/$/, '');
  const bySymbol = new Map<string, { dates: string[]; closes: number[] } | null>();
  let updated = 0;
  for (const sym of [...new Set(targets.map((r) => r.symbol.toUpperCase()))].slice(0, 20)) {
    const mkt = /^\d/.test(sym) ? 'JP' : 'US';
    try {
      const r = await fetch(`${base}/api/argus/price-history?symbol=${encodeURIComponent(sym)}&market=${mkt}`);
      const d = await r.json();
      bySymbol.set(sym, d.available ? { dates: d.dates, closes: d.closes } : null);
    } catch { bySymbol.set(sym, null); }
  }
  const now = new Date().toISOString();
  for (const rec of targets) {
    const h = bySymbol.get(rec.symbol.toUpperCase());
    const o = h
      ? computeOutcome(rec.priceAtDecision, rec.asOf.slice(0, 10), h.dates, h.closes, now)
      : { ...computeOutcome(rec.priceAtDecision, rec.asOf.slice(0, 10), [], [], now) };
    if (o.outcomeStatus === 'partial' || o.outcomeStatus === 'complete') {
      const it = interpretOutcome(rec, o);
      o.outcomeInterpretation = it.interpretation;
      o.outcomeReadableJa = it.ja;
      // keep the v11.9.0 placeholder fields in sync (future-return contract)
      rec.futureReturn1d = o.outcomeReturn1d;
      rec.futureReturn3d = o.outcomeReturn3d;
      rec.futureReturn5d = o.outcomeReturn5d;
      rec.futureReturn20d = o.outcomeReturn20d;
      updated++;
    }
    rec.outcome = o;    // evidence fields untouched — outcome/annotation only
  }
  saveAll(recs);
  writeMeta({ lastOutcomeUpdateAt: now });
  return updated;
}

// ── owner annotation (local-only, optional, never inferred) ─────────────────

export function annotateOwnerAction(id: string,
  action: 'bought' | 'sold' | 'added' | 'trimmed' | 'held' | 'watched' | 'skipped',
  note?: string): boolean {
  const recs = listDQ();
  const r = recs.find((x) => x.id === id);
  if (!r) return false;
  r.ownerAction = action;
  r.ownerActionNote = note ?? null;
  r.ownerActionAt = new Date().toISOString();
  saveAll(recs);
  return true;
}

export const OWNER_ACTION_JA: Record<string, string> = {
  bought: '買った', added: '買い増した', sold: '売った', trimmed: '減らした',
  held: '持ち続けた', watched: '見ていた', skipped: '見送った',
};

// ── summary / per-asset history / handoff text ──────────────────────────────

export interface DQSummary {
  total: number; pending: number; withOutcome: number;
  supported: number; contradicted: number; mixed: number; inconclusive: number;
  notEnoughHistory: boolean;
}

export function dqSummary(): DQSummary {
  const recs = listDQ();
  const it = (r: DQRecord) => r.outcome?.outcomeInterpretation;
  const judged = recs.filter((r) => it(r) === 'supported' || it(r) === 'contradicted');
  return {
    total: recs.length,
    pending: recs.filter((r) => !r.outcome || r.outcome.outcomeStatus === 'pending').length,
    withOutcome: recs.filter((r) => r.outcome && (r.outcome.outcomeStatus === 'partial' || r.outcome.outcomeStatus === 'complete')).length,
    supported: recs.filter((r) => it(r) === 'supported').length,
    contradicted: recs.filter((r) => it(r) === 'contradicted').length,
    mixed: recs.filter((r) => it(r) === 'mixed').length,
    inconclusive: recs.filter((r) => it(r) === 'inconclusive').length,
    notEnoughHistory: judged.length < 5,
  };
}

export function decisionHistoryFor(symbol: string, limit = 3): DQRecord[] {
  const symU = symbol.toUpperCase();
  return listDQ().filter((r) => r.symbol.toUpperCase() === symU)
    .sort((a, b) => (a.asOf < b.asOf ? 1 : -1)).slice(0, limit);
}

/** Pro Handoff / AI Review Sheet — device-local historical-check lines. */
export function dqHandoffTextJa(): string {
  const s = dqSummary();
  if (s.total === 0) return '## Decision Quality / Historical Check\n記録なし(日次スナップショット作成時に自動記録されます)。';
  const L = ['## Decision Quality / Historical Check',
    `記録${s.total}件 / 結果待ち${s.pending} / 検証可${s.withOutcome} — 支持${s.supported} · 反証${s.contradicted} · 中間${s.mixed} · 保留${s.inconclusive}`];
  for (const r of listDQ().filter((x) => x.outcome?.outcomeReadableJa).slice(0, 4)) {
    L.push(`- ${r.symbol} [${r.decisionContext}] ${r.outcome!.outcomeReadableJa}`);
  }
  if (s.notEnoughHistory) L.push('注意: まだ履歴が浅く、成績として扱わないこと(参考情報)。');
  return L.join('\n');
}
