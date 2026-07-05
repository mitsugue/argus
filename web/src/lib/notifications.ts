// V11.14.0 — Notification engine (device-local TS port of argus_notifications.py).
// 変化があった時だけ静かに知らせる。通知は端末内で生成・保存され(暗号化バック
// アップに同乗)、サーバーには一切送られない。売買指示ではない。

import type { APItem } from '../domain/actionPriority';
import { jpDisplay } from './displayName';

export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';
const SEV_ORDER: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
export const SEV_JA: Record<Severity, string> = {
  critical: '最優先', high: '重要', medium: '注意', low: '参考', info: '情報',
};
export const SEV_TONE: Record<Severity, string> = {
  critical: 'var(--value-negative)', high: 'var(--amber, #fbbf24)',
  medium: 'var(--accent)', low: 'var(--text-muted)', info: 'var(--text-faint)',
};

export interface AppNotification {
  id: string; createdAt: string;
  eventType: string; severity: Severity;
  symbol: string | null; assetName: string | null;
  titleJa: string; bodyJa: string; whyJa: string; checkNextJa: string;
  deliveryState: 'new' | 'seen' | 'dismissed';
  dedupeKey: string; isPrivate: boolean;
}

const STORE_KEY = 'argus.notifications.v1';
const CAP = 100;
const GLOBAL_MAX_PER_DAY = 12;
const RULES: Record<string, { severity: Severity; cooldownMin: number; maxPerDay: number }> = {
  p0_priority: { severity: 'critical', cooldownMin: 60, maxPerDay: 5 },
  p1_held_priority: { severity: 'high', cooldownMin: 1440, maxPerDay: 5 },
  event_before: { severity: 'medium', cooldownMin: 720, maxPerDay: 4 },
  flow_deterioration: { severity: 'high', cooldownMin: 720, maxPerDay: 5 },
  supply_demand_deterioration: { severity: 'high', cooldownMin: 1440, maxPerDay: 4 },
  supply_demand_improvement: { severity: 'low', cooldownMin: 1440, maxPerDay: 3 },
  squeeze_watch: { severity: 'medium', cooldownMin: 1440, maxPerDay: 3 },
  scenario_change: { severity: 'high', cooldownMin: 1440, maxPerDay: 3 },
  plan_change: { severity: 'high', cooldownMin: 1440, maxPerDay: 3 },
  strategy_risk: { severity: 'high', cooldownMin: 4320, maxPerDay: 2 },
  avoid_chase: { severity: 'medium', cooldownMin: 1440, maxPerDay: 4 },
  session_brief_ready: { severity: 'info', cooldownMin: 240, maxPerDay: 3 },
  snapshot_missing: { severity: 'low', cooldownMin: 1440, maxPerDay: 1 },
  sync_backup_warning: { severity: 'low', cooldownMin: 4320, maxPerDay: 1 },
  restore_not_verified: { severity: 'low', cooldownMin: 10080, maxPerDay: 1 },
};

interface Store {
  items: AppNotification[];
  lastByDedupe: Record<string, string>;
  sentToday: { day: string; total: number; byType: Record<string, number> };
  prev: PrevState;
}
export interface PrevState {
  p0?: string[]; p1Held?: string[]; chase?: string[]; events?: string[];
  flow?: Record<string, string>; sd?: Record<string, { rank: string; condition: string }>;
  scenario?: Record<string, string>;
  plan?: Record<string, string>;
  strategy?: { tactical?: string; single?: string; theme?: string; fire?: string };
  briefSession?: string;
}

function load(): Store {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Store;
  } catch { /* fresh */ }
  return { items: [], lastByDedupe: {}, sentToday: { day: '', total: 0, byType: {} }, prev: {} };
}
function save(s: Store): void {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); } catch { /* quota */ }
}

const jstNow = () => new Date(Date.now() + 9 * 3600_000);
const jstDay = () => jstNow().toISOString().slice(0, 10);

export interface NotifInputs {
  apItems: APItem[];
  eventNames: string[];
  sdBySymbol: Record<string, { rank: string; condition: string; level?: string;
    name?: string; isHeld?: boolean }>;
  flowBySymbol: Record<string, { flowClass: string; name?: string; isHeld?: boolean }>;
  /** v11.17.0: 支配シナリオ(端末内合成)。保有×弱気転換のみ通知(それ以外はノイズ)。 */
  scenarioBySymbol?: Record<string, { dominant: string; name?: string;
    isHeld?: boolean; summaryJa?: string }>;
  /** v11.18.0: 計画(端末内合成)。materialな転換のみ通知: 保有×リスク確認/利確検討入り・追加候補→追いかけ注意。 */
  planBySymbol?: Record<string, { planType: string; currentStance: string;
    name?: string; isHeld?: boolean; summaryJa?: string }>;
  /** v11.19.0: 戦略リスク(端末内合成)。materialな悪化転換のみ通知。 */
  strategyState?: { tactical: string; single: string; theme: string; fire: string;
    summaryJa?: string } | null;
  briefSession: string;
  hasHoldings: boolean;
  snapshotAgeDays: number | null;
  vaultConfigured: boolean;
  restoreVerified?: boolean;
}

/** Run once per Today mount (throttled by dedupe/cooldowns internally). */
let _lastRunMs = 0;
export function runNotificationEngine(inp: NotifInputs): { delivered: number } {
  if (Date.now() - _lastRunMs < 60_000) return { delivered: 0 };   // no polling spam
  _lastRunMs = Date.now();
  const st = load();
  const now = new Date().toISOString();
  const day = jstDay();
  const cands: Omit<AppNotification, 'id' | 'createdAt' | 'deliveryState'>[] = [];
  const nm = (sym: string | null, name?: string | null) => sym ? jpDisplay(sym, name ?? undefined) : '';

  const p0Now = inp.apItems.filter((i) => i.priorityRank === 'P0').map((i) => i.symbol);
  const p1HeldNow = inp.apItems.filter((i) => i.priorityRank === 'P1' && i.isHeld).map((i) => i.symbol);
  const chaseNow = inp.apItems.filter((i) => i.category === 'avoid_chase').map((i) => i.symbol);

  for (const it of inp.apItems) {
    if (it.priorityRank === 'Ignore') continue;
    if (it.priorityRank === 'P0' && !(st.prev.p0 ?? []).includes(it.symbol)) {
      cands.push({ eventType: 'p0_priority', severity: 'critical', symbol: it.symbol,
        assetName: it.assetName, titleJa: `最優先確認：${nm(it.symbol, it.assetName)}`,
        bodyJa: `保有中の${nm(it.symbol, it.assetName)}に複数のリスク信号が重なっています。`,
        whyJa: it.whyJa, checkNextJa: it.checkNextJa,
        dedupeKey: `p0|${it.symbol}|${day}`, isPrivate: it.isHeld });
    } else if (it.priorityRank === 'P1' && it.isHeld && !(st.prev.p1Held ?? []).includes(it.symbol)
      && !(st.prev.p0 ?? []).includes(it.symbol)) {
      cands.push({ eventType: 'p1_held_priority', severity: 'high', symbol: it.symbol,
        assetName: it.assetName, titleJa: `保有銘柄の優先確認：${nm(it.symbol, it.assetName)}`,
        bodyJa: `${nm(it.symbol, it.assetName)}は今日確認が必要です。`,
        whyJa: it.whyJa, checkNextJa: it.checkNextJa,
        dedupeKey: `p1|${it.symbol}|${day}`, isPrivate: true });
    }
    if (it.category === 'avoid_chase' && !(st.prev.chase ?? []).includes(it.symbol)) {
      cands.push({ eventType: 'avoid_chase', severity: 'medium', symbol: it.symbol,
        assetName: it.assetName, titleJa: `追いかけ注意：${nm(it.symbol, it.assetName)}`,
        bodyJa: '上昇していますが、買い戻し主導/過熱の可能性があります。',
        whyJa: it.whyJa, checkNextJa: it.checkNextJa,
        dedupeKey: `chase|${it.symbol}`, isPrivate: it.isHeld });
    }
  }
  for (const ev of inp.eventNames) {
    if (!(st.prev.events ?? []).includes(ev)) {
      cands.push({ eventType: 'event_before', severity: 'medium', symbol: null, assetName: null,
        titleJa: `イベント前：${ev}`,
        bodyJa: `${ev}発表前のため、関連銘柄の買い増し判断は発表後の反応確認まで待機。`,
        whyJa: '重要イベントは初動反応で判断が変わるため。',
        checkNextJa: `${ev}の結果と直後の金利・指数反応を確認`,
        dedupeKey: `evb|${ev}|${day}`, isPrivate: false });
    }
  }
  for (const [sym, f] of Object.entries(inp.flowBySymbol)) {
    const was = (st.prev.flow ?? {})[sym];
    if ((f.flowClass === 'panic_selling' || f.flowClass === 'distribution')
      && was !== 'panic_selling' && was !== 'distribution') {
      cands.push({ eventType: 'flow_deterioration', severity: f.isHeld ? 'high' : 'medium',
        symbol: sym, assetName: f.name ?? null,
        titleJa: `Flow悪化：${nm(sym, f.name)}`,
        bodyJa: '大口流出/売り抜け/狼狽売りの可能性が出ています。',
        whyJa: '実測フロー/値動きの型が売り圧力側に変化。',
        checkNextJa: '翌営業日に戻りが売られるか、公式材料を確認',
        dedupeKey: `flow|${sym}|${f.flowClass}`, isPrivate: !!f.isHeld });
    }
  }
  for (const [sym, sd] of Object.entries(inp.sdBySymbol)) {
    const was = (st.prev.sd ?? {})[sym] ?? { rank: '', condition: '' };
    if ((sd.rank === 'D' || sd.rank === 'E') && was.rank !== 'D' && was.rank !== 'E') {
      cands.push({ eventType: 'supply_demand_deterioration', severity: sd.isHeld ? 'high' : 'medium',
        symbol: sym, assetName: sd.name ?? null,
        titleJa: `需給悪化：${nm(sym, sd.name)}`,
        bodyJa: '信用買い残が重く、戻り売りに注意。', whyJa: '需給ランクがD/Eに移行。',
        checkNextJa: '戻り局面で売りが出るかを確認',
        dedupeKey: `sdD|${sym}|${sd.rank}`, isPrivate: !!sd.isHeld });
    } else if (sd.condition === 'squeeze_prone' && was.condition !== 'squeeze_prone') {
      cands.push({ eventType: 'squeeze_watch', severity: 'medium', symbol: sym,
        assetName: sd.name ?? null, titleJa: `踏み上げ注意：${nm(sym, sd.name)}`,
        bodyJa: '売り長で踏み上げ余地。買い戻し主導の可能性があり新規の大口買いとは未確定。',
        whyJa: '貸借倍率が売り長側。', checkNextJa: '買い戻し一巡後に失速しないかを確認',
        dedupeKey: `sq|${sym}`, isPrivate: !!sd.isHeld });
    } else if (['S', 'A', 'B'].includes(sd.rank) && ['C', 'D', 'E', 'Unknown'].includes(was.rank || 'Unknown') && was.rank) {
      const heavy = sd.level === 'heavy' || sd.level === 'very_heavy' || sd.condition === 'improving_but_heavy';
      cands.push({ eventType: 'supply_demand_improvement', severity: 'low', symbol: sym,
        assetName: sd.name ?? null,
        titleJa: heavy ? `需給改善方向：${nm(sym, sd.name)}` : `需給改善：${nm(sym, sd.name)}`,
        bodyJa: heavy ? '需給は改善方向ですが、信用買い残はまだ重いです。'
          : `需給ランクが${sd.rank}に改善しました。`,
        whyJa: heavy ? '買い残は減少中だが絶対量が大きい。' : '買い残水準・売り圧力が軽い状態。',
        checkNextJa: heavy ? '買い残が続けて減るか、上昇日に出来高を伴うかを確認' : '続伸時の出来高を確認',
        dedupeKey: `sdUp|${sym}|${day}`, isPrivate: !!sd.isHeld });
    }
  }
  // v11.19.0: strategy_risk — 戦略リスクのmaterialな悪化転換のみ:
  // 戦術枠→超過 / 1銘柄集中→critical / テーマ集中→critical / FIRE整合の悪化。
  // 初回(prev無し)は記録のみ。改善方向は通知しない(ノイズ)。
  if (inp.strategyState && st.prev.strategy) {
    const cur = inp.strategyState, was = st.prev.strategy;
    const trans: [string, string, string][] = [];
    if (cur.tactical === 'exceeded' && was.tactical !== 'exceeded') {
      trans.push(['tactical', '短期勝負枠が超過しました',
        '新規追加よりも、既存ポジションの集中度とイベントリスクの確認が先です。']);
    }
    if (cur.single === 'critical' && was.single !== 'critical') {
      trans.push(['single', '1銘柄集中が危険水準になりました',
        '追加の前に、この銘柄の比率上限を確認してください。']);
    }
    if (cur.theme === 'critical' && was.theme !== 'critical') {
      trans.push(['theme', 'テーマ集中が危険水準になりました',
        'AI関連が同時に下がる前提での比率確認が先です。']);
    }
    if (['stretched', 'misaligned'].includes(cur.fire)
      && !['stretched', 'misaligned'].includes(was.fire ?? '')) {
      trans.push(['fire', 'FIRE整合が悪化しました',
        '個別株の判断とは別に、コア(積立)比率の確認を。']);
    }
    for (const [key, title, body] of trans) {
      cands.push({ eventType: 'strategy_risk', severity: 'high', symbol: null,
        assetName: null, titleJa: `戦略注意：${title}`,
        bodyJa: inp.strategyState.summaryJa?.slice(0, 80) || body,
        whyJa: body, checkNextJa: 'Core Portfolio → PORTFOLIO STRATEGYで詳細確認(助言ではない)',
        dedupeKey: `strat|${key}`, isPrivate: true });
    }
  }
  // v11.18.0: plan_change — materialな計画転換のみ: ①保有×(リスク確認/利確検討)
  // 入り ②追加候補(押し目限定/小さく可)→追いかけ注意。毎計画では鳴らさない。
  for (const [sym, pl] of Object.entries(inp.planBySymbol ?? {})) {
    const was = (st.prev.plan ?? {})[sym];
    if (!was) continue;                               // 初回は記録のみ(初期化スパム防止)
    const nowRisk = ['risk_review', 'trim_consideration'].includes(pl.currentStance);
    const wasRisk = ['risk_review', 'trim_consideration'].includes(was);
    const wasAddSide = ['add_only_on_pullback', 'small_add_allowed'].includes(was);
    if (pl.isHeld && nowRisk && !wasRisk) {
      cands.push({ eventType: 'plan_change', severity: 'high', symbol: sym,
        assetName: pl.name ?? null,
        titleJa: `計画転換：${nm(sym, pl.name)}は${pl.currentStance === 'trim_consideration' ? '一部利確を検討する局面' : 'リスク確認が先'}に`,
        bodyJa: pl.summaryJa?.slice(0, 80) || '保有銘柄の計画がリスク確認側に切り替わりました。',
        whyJa: '悪化信号(需給/フロー/シナリオ)が重なったため。',
        checkNextJa: '銘柄カードのPOSITION PLANで条件と無効化条件を確認',
        dedupeKey: `plan|${sym}|risk`, isPrivate: true });
    } else if (wasAddSide && pl.currentStance === 'avoid_chase') {
      cands.push({ eventType: 'plan_change', severity: 'medium', symbol: sym,
        assetName: pl.name ?? null,
        titleJa: `計画転換：${nm(sym, pl.name)}は追いかけ買い注意に`,
        bodyJa: '追加候補でしたが、過熱/買い戻し主導の可能性が出たため待ちに変更。',
        whyJa: '上昇の持続性が未確認になったため。',
        checkNextJa: '出来高を伴う押し目か、上昇主体の入れ替わりを確認',
        dedupeKey: `plan|${sym}|chase`, isPrivate: !!pl.isHeld });
    }
  }
  // v11.17.0: scenario_change — 保有銘柄の支配シナリオが弱気に転換した時だけ。
  // 監視銘柄・弱気→改善方向はここでは通知しない(材料が出れば他ルールが拾う)。
  for (const [sym, sc] of Object.entries(inp.scenarioBySymbol ?? {})) {
    const was = (st.prev.scenario ?? {})[sym];
    if (sc.isHeld && sc.dominant === 'bearish' && was && was !== 'bearish') {
      cands.push({ eventType: 'scenario_change', severity: 'high', symbol: sym,
        assetName: sc.name ?? null,
        titleJa: `シナリオ転換：${nm(sym, sc.name)}が弱気優勢に`,
        bodyJa: sc.summaryJa?.slice(0, 80) || '複数レイヤーの悪化が重なり、支配シナリオが弱気側に切り替わりました。',
        whyJa: '需給・フロー等の条件付き分岐で弱気側の成立条件が優勢になったため。',
        checkNextJa: '銘柄カードのSCENARIOSで無効化条件と次の確認を参照',
        dedupeKey: `scn|${sym}|bearish`, isPrivate: true });
    }
  }
  if (inp.briefSession && inp.briefSession !== st.prev.briefSession) {
    cands.push({ eventType: 'session_brief_ready', severity: 'info', symbol: null, assetName: null,
      titleJa: '今日の作戦が更新されました。',
      bodyJa: 'SESSION BRIEFで今日のモードと「やらないこと」を確認してください。',
      whyJa: 'セッションが切り替わりました。', checkNextJa: 'SESSION BRIEFを確認',
      dedupeKey: `brief|${inp.briefSession}|${day}`, isPrivate: false });
  }
  if (inp.hasHoldings) {
    if (inp.snapshotAgeDays == null || inp.snapshotAgeDays > 3) {
      cands.push({ eventType: 'snapshot_missing', severity: 'low', symbol: null, assetName: null,
        titleJa: 'バックアップ確認：スナップショット未作成',
        bodyJa: '保有データのスナップショットが最近作成されていません。',
        whyJa: '履歴が残らないと後日の答え合わせができません。',
        checkNextJa: 'Todayを開けば自動作成されます', dedupeKey: `snap|${day}`, isPrivate: true });
    }
    if (inp.restoreVerified === false && inp.vaultConfigured) {
      cands.push({ eventType: 'restore_not_verified', severity: 'low', symbol: null, assetName: null,
        titleJa: '復元未確認', bodyJa: 'バックアップから戻せることを一度も確認していません。復元ドリル(非破壊)を実行してください。',
        whyJa: '復元できないバックアップは保護になりません。', checkNextJa: 'Core Portfolio → BACKUP SAFETY → 復元ドリルを実行',
        dedupeKey: 'drill', isPrivate: true });
    }
    if (!inp.vaultConfigured) {
      cands.push({ eventType: 'sync_backup_warning', severity: 'low', symbol: null, assetName: null,
        titleJa: 'バックアップ未設定',
        bodyJa: '暗号化バックアップ(パスフレーズ)が未設定です。端末故障で保有データが失われます。',
        whyJa: '保有・判断履歴は端末内のみ。', checkNextJa: 'Guideの「バックアップと同期」で設定',
        dedupeKey: 'vault', isPrivate: true });
    }
  }

  // ── noise control ──
  const hour = jstNow().getUTCHours();
  const wd = jstNow().getUTCDay();
  const quiet = hour >= 23 || hour < 6;
  const weekend = wd === 0 || wd === 6;
  if (st.sentToday.day !== day) st.sentToday = { day, total: 0, byType: {} };
  let delivered = 0;
  for (const c of cands.sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity])) {
    const rule = RULES[c.eventType] ?? { severity: 'info' as Severity, cooldownMin: 1440, maxPerDay: 2 };
    if (quiet && c.severity !== 'critical') continue;
    if (weekend && SEV_ORDER[c.severity] > SEV_ORDER.high
      && !['snapshot_missing', 'sync_backup_warning', 'session_brief_ready'].includes(c.eventType)) continue;
    const last = st.lastByDedupe[c.dedupeKey];
    if (last && (Date.now() - Date.parse(last)) / 60000 < rule.cooldownMin) continue;
    if ((st.sentToday.byType[c.eventType] ?? 0) >= rule.maxPerDay) continue;
    if (st.sentToday.total >= GLOBAL_MAX_PER_DAY && c.severity !== 'critical') continue;
    st.items.unshift({ ...c, id: `nt-${Date.now()}-${delivered}`, createdAt: now, deliveryState: 'new' });
    st.lastByDedupe[c.dedupeKey] = now;
    st.sentToday.byType[c.eventType] = (st.sentToday.byType[c.eventType] ?? 0) + 1;
    st.sentToday.total += 1;
    delivered++;
  }
  st.items = st.items.slice(0, CAP);
  st.prev = {
    p0: p0Now, p1Held: p1HeldNow, chase: chaseNow, events: inp.eventNames,
    flow: Object.fromEntries(Object.entries(inp.flowBySymbol).map(([k, v]) => [k, v.flowClass])),
    sd: Object.fromEntries(Object.entries(inp.sdBySymbol).map(([k, v]) => [k, { rank: v.rank, condition: v.condition }])),
    scenario: Object.fromEntries(Object.entries(inp.scenarioBySymbol ?? {}).map(([k, v]) => [k, v.dominant])),
    plan: Object.fromEntries(Object.entries(inp.planBySymbol ?? {}).map(([k, v]) => [k, v.currentStance])),
    strategy: inp.strategyState ? { tactical: inp.strategyState.tactical,
      single: inp.strategyState.single, theme: inp.strategyState.theme,
      fire: inp.strategyState.fire } : st.prev.strategy,
    briefSession: inp.briefSession,
  };
  save(st);
  return { delivered };
}

export function listNotifications(): AppNotification[] {
  return load().items.filter((i) => i.deliveryState !== 'dismissed');
}
export function unreadCounts(): { total: number; critical: number; high: number } {
  const unread = load().items.filter((i) => i.deliveryState === 'new');
  return { total: unread.length,
    critical: unread.filter((i) => i.severity === 'critical').length,
    high: unread.filter((i) => i.severity === 'high').length };
}
export function markAllSeen(): void {
  const st = load();
  for (const i of st.items) if (i.deliveryState === 'new') i.deliveryState = 'seen';
  save(st);
}
export function dismissNotification(id: string): void {
  const st = load();
  const it = st.items.find((x) => x.id === id);
  if (it) it.deliveryState = 'dismissed';
  save(st);
}

/** Pro Handoff / AI Review — attention changes (device-local). */
export function ntHandoffTextJa(): string {
  const items = listNotifications().filter((i) => i.deliveryState !== 'dismissed').slice(0, 5);
  if (!items.length) return '## Notifications / Attention Changes\n新しい注意喚起はありません。';
  const L = ['## Notifications / Attention Changes'];
  for (const i of items) L.push(`- [${SEV_JA[i.severity]}] ${i.titleJa} — ${i.bodyJa.slice(0, 60)}`);
  L.push('注意: 注意喚起であり売買指示ではない。');
  return L.join('\n');
}
