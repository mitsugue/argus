import React, { useState } from 'react';
import { latestExposure } from '../lib/positionExposureShare';
import { exposureSummaryText } from '../domain/positionExposure';
import { backupStatusTextJa } from '../lib/portfolioSync';
import { dqHandoffTextJa } from '../lib/decisionQuality';
import { latestActionPriorities } from '../lib/positionExposureShare';
import { apHandoffTextJa } from '../domain/actionPriority';
import { sbHandoffTextJa } from '../domain/sessionBrief';
import { latestSessionBrief } from '../lib/positionExposureShare';
import { ntHandoffTextJa } from '../lib/notifications';
import { lrHandoffTextJa } from '../lib/learningReview';
import { latestScenarios } from '../lib/positionExposureShare';
import { scHandoffTextJa } from '../domain/scenario';
import { ActionPill } from '../components/action/ActionBadge';
import { ACTIONS, ACTION_ORDER, CORE_ACTIONS, CORE_ACTION_ORDER } from '../domain/actions';
import type { ActionKey, CoreActionKey } from '../types/action';
import { downloadBackup, BACKUP_KEYS } from '../lib/backup';
import './AIReview.css';

// One-page review sheet. Built for LLM eval (ChatGPT etc.): self-contained
// descriptive content + a "Copy markdown" button so the reviewer can paste
// the whole thing into a chat without scraping the DOM.

const PALETTE = [
  ['--bg',           '#0B1118', 'app background'],
  ['--surface',      '#111A24', 'card surface'],
  ['--surface-soft', '#162231', 'hover / active surface'],
  ['--line',         'rgba(255,255,255,0.07)', 'subtle divider'],
  ['--text-main',    '#E6EDF3', 'primary text'],
  ['--text-sub',     '#8B98A7', 'secondary text'],
  ['--text-muted',   '#5F6B78', 'meta text'],
  ['--red',          '#F87171', 'EXIT / high risk / outflow'],
  ['--amber',        '#FBBF24', 'TRIM / medium risk'],
  ['--blue',         '#60A5FA', 'WAIT_FOR_PULLBACK / regime accent'],
  ['--cyan',         '#22D3EE', 'BUY_DIP / GRADUAL_ADD'],
  ['--green',        '#34D399', 'ADD / CONTINUE / low risk / inflow'],
  ['--gray',         '#64748B', 'WAIT / DEFER_LUMP_SUM / NO_SELL_ACTION'],
];

const ROUTES = [
  ['Today',         'Daily Command Center — hero judgment + Top Rotations + compact priority watchlist + compact event preview + compact core preview'],
  ['Action Alerts', 'Core and satellite asset-class cards with full reasoning, supporting data, and next condition'],
  ['Market Regime', 'Capital Rotation Board (primary, live rule-based scoring) + Regime Matrix (Growth↔Defensive × Risk↔Duration) + Regime Summary + glossary, wired to live /api/argus/market-regime (regime-v1). The old bubble visualization is retired from the main experience'],
  ['Event Radar',   'Upcoming events list + D-7 → D+1 escalation policy'],
  ['Watchlist',     'Dense JP / US watchlist rows with action label, news, scanner rationale, and urgency sorting'],
  ['Core Portfolio','Long-term index status with calm vocabulary (Continue / Gradual Add / Defer Lump Sum / No Sell Action)'],
];

const KEPT = [
  'AppShell — slim header, persistent sidebar (Today\'s call pill stable across pages)',
  'Theme token structure (palette swapped, shape preserved)',
  'Backend scanner.py + argus_ledger.py — now wired live (FRED rates, J-Quants JP + Twelve Data US watchlists, Event Radar, Action Labels, Corporate Catalysts, Market Regime / Capital Rotation v1, Pro Handoff)',
  'English chrome + Japanese market commentary balance',
];

const REPLACED = [
  'Capital Concentration → Regime Matrix + Capital Rotation Board',
  'SectorBlob as main Market Regime visual → retired (optional legacy only if it ever earns its keep)',
  'Dense Today preview → compact command summary (full detail moved to detail pages)',
  'Today reasons that literally repeated "CPI in 24h" → interpretive reasons (event window, rates pressure, overnight momentum)',
  'WAIT_LUMP → DEFER_LUMP_SUM, NO_SELL → NO_SELL_ACTION',
];

const DROPPED = [
  'Sticky Notes (investment focus over memos)',
  'HUD ornaments: clock, UPLINK MOCK pill, crosshairs',
  'Orbitron / Share Tech Mono / Michroma fonts',
  'Sci-fi letter-spacing (4px+) on body and headings',
  'Design-system-preview as the home page',
  '3D / force-graph visual concepts from the active UI',
  'Bubble visualization as the primary Market Regime interface',
];

const OPEN_QUESTIONS = [
  'Is the calm aesthetic carrying enough authority for serious investment use, or too muted?',
  'Watchlist row density: is JP/US dense-line right, or should rows expand on click for full data?',
  'Action vocabulary: are 7 tactical labels enough, or do we need sub-actions (e.g., "trim 1/3" vs "trim 1/2")?',
  'Cross-page navigation: enough handles (Today\'s call pill, Next event chip, section-head links), or missing connections?',
  'JP/EN mix: working as an intentional bilingual structure, or confusing? Should there be a global EN-only toggle?',
  'Should asset-class display names (Japan Individual Stocks etc.) also be JP, or stay structural English?',
  'Are the Regime Matrix and Capital Rotation Board clear enough to replace the old bubble visualization?',
  'Is the Capital Rotation Board readable at a glance without numeric values, or does it need a minimal score indicator?',
];

const GAPS = [
  'Filter chips on Watchlist (e.g., "show EXIT only") — not built yet',
  'Automated AI judgment (GPT-5.5 primary + a runtime-configured Gemini checker — the actual model/status comes from /ai-provider-status, not hardcoded) runs daily via the prediction-ledger cron when the ARGUS_ADMIN_TOKEN repo secret is set; per-symbol AI views appear in strategy cards while the cache is fresh (30-min TTL after each run — between runs the public GET honestly reports no_cached_result). Action labels remain rule-based with AI as a recorded second opinion; the GPT-5.5 Pro Handoff stays manual copy-paste (no API call)',
  'Cost/provider truth (v10.50): AI spend is hard-capped on the ARGUS side (daily/monthly USD budget, env-tunable) — the OpenAI prepaid balance is NOT the stop; runs are rejected once the ceiling is hit, with estimated cost + the ACTUAL model recorded. Gemini 2.5 Pro is the routine checker; Flash is only a 429 fallback (not merged in calibration). Twelve Data Basic regular-session US equities are real-time (not asserted "delayed" without runtime evidence); kept as fallback, no upgrade. EDINET is an official FACT but only a materially-relevant same-day filing becomes the official_catalyst — EDINET is not equivalent to TDnet, which remains unsubscribed (objective purchase metrics now tracked). Market-data display is intended owner-only; real backend auth is a pending separate patch (today the GitHub Pages app + most data endpoints are still publicly reachable)',
  'Market Regime ETF universe is a focused 8-symbol proxy subset (SPY/QQQ/IWM/XLK/XLU/GLD/TLT/HYG) — financials/energy/semis and the LQD credit pair are pending; ETF rotation is a proxy for capital flow, not direct flow',
  'Japan regime uses watchlist breadth as a temporary proxy, not index/sector rotation',
  'moomoo big-money capital flow is shipped (v10.2, bridge update required on the OpenD box); order book / tape / VWAP still pending',
  'Outcome tracking IS live (v10.24+): the Prediction Ledger scores each day\'s falsifiable predictions vs realized moves on the GitHub `ledger` branch (argmax hit + Brier, layer-separated 1/3/5-day horizons), plus a Scout calibration ledger and a same-day Close-Pin ledger. Caveat: n counts predictions, not independent trials — same-day/same-theme names are correlated, so effective sample is smaller than the raw count. The device-local judgment log (localStorage) is a separate personal note, not the scored record',
  'Market Regime now holds the last full-coverage reading when ETF data is partial (v10.34) so the label does not flip on Twelve Data rate-limit noise; a full regime-shift audit trail (why it changed) is still pending',
  'No history of past Top Rotations',
  'No user-specific exposure weighting across asset classes',
  'Portfolio Exposure + What-if simulator are SHIPPED (v10.0/v10.1, device-local by design) — remaining: cross-device sync, fund NAV valuation',
  'Watchlist config is localStorage-only (per device; no cross-device sync)',
];

function runtimeBlock(m: any): string {
  if (!m) return '';
  const p = m.providers || {}; const d = m.downside || {}; const td = m.tdnet || {};
  return `## RUNTIME (live — read this FIRST; the static sections below may lag)

- **App build:** ${m.buildSha ?? '—'} · **asOf:** ${m.asOf ?? '—'}
- **Active routes (5):** ${(m.activeRoutes || []).join(' · ')}
- **Providers:** ${p.confirmedLive ?? '—'}/${p.total ?? '—'} confirmed live${(p.degraded || []).length ? ` · degraded: ${(p.degraded || []).join(', ')}` : ''}
- **Calibration:** ${m.calibration?.phase ?? '—'} (universe ${m.calibration?.universe ?? '—'}, cohort ${m.calibration?.cohort ?? '—'})
- **Downside layer:** ${d.engine ?? '—'} · active incidents ${d.activeIncidents ?? 0} · JP overlay ${d.jpIntradayOverlay ?? '—'} · holder ${d.holderRiskOverlay ?? '—'}
  - rule: ${d.rule ?? ''}
- **TDnet (適時開示):** ${td.status ?? '—'}${td.count ? ` (${td.count})` : ''} via ${td.provider ?? '—'}
- **Owner watchlist (Layer 2B):** configured=${m.ownerWatchlist?.layer2bConfigured} · ${m.ownerWatchlist?.note ?? ''}
- **Decision Value:** ${m.decisionValue?.phase ?? '—'} (shadow simulation only; no order/broker/execute routes)
- **Visibility Risk:** ${m.visibility?.visibilityLevel ?? '—'}${m.visibility?.confidenceCap != null ? ` · confidence cap ${m.visibility.confidenceCap}` : ''} · codes: ${(m.visibility?.reasonCodes || []).join(', ') || '—'}
- **AI judgment:** ${m.ai?.status ?? '—'} · ${m.ai?.note ?? ''}
- **Safety:** ${(m.safetyBoundaries || []).join('; ')}
- **Current limitations:** ${(m.currentLimitations || []).map((x: string) => `\n  - ${x}`).join('')}

---

`;
}

function buildMarkdown(version: string, manifest?: any): string {
  return `# A.R.G.U.S. — AI Review Sheet (v${version})

${runtimeBlock(manifest)}` + `
` + baseMarkdown(version);
}

function baseMarkdown(version: string): string {
  return `<!-- static spec (v${version}); see RUNTIME above for current state -->

**Identity.** A.R.G.U.S. = Autonomous Risk and Global Uncertainty Scanner. A personal action-decision engine for daily investing. Not a chart app. Not a visual toy. **A calm investment command center that classifies market conditions into action categories, with market visuals serving as evidence rather than spectacle.** Answers: what is today's call, what is the risk, why, what to touch, what to avoid, what to wait for next — and what would change the current posture.

**Live URL.** https://mitsugue.github.io/argus/

**Primary product shift (v8.0 → v8.1).** v8 retires the old capital-flow visualization-first approach. The product center is now action judgment. Market visuals (Regime Matrix, Capital Rotation Board, Top Rotations) exist only to support decisions, not to become the main experience. The bubble / SectorBlob viz is retired from the main UI.

---

## Market visuals rule

Market visuals must never become the primary experience. They should always answer one of three questions:

1. Where is capital rotating?
2. What regime are we in?
3. How does this support the current action labels?

Visuals are supporting evidence, not trading signals by themselves. This rule exists because older versions of A.R.G.U.S. were too focused on visualizing capital flow; v8.1 keeps visuals only as decision-support tools.

---

## Design philosophy

- Bloomberg Terminal + Linear + Raycast + Stripe Dashboard
- Dark navy, calm, professional. No HUD, no cyberpunk, no neon glow
- No decorative crosshairs, no fake terminal chrome, no Orbitron brand
- Single primary action visually dominant; secondary state quiet
- 10-second rule: user understands today's call within 10 seconds of opening the app
- Intentional bilingual structure: English chrome for system clarity, Japanese content for market commentary, news, scanner rationale, and user-facing investment reasoning

---

## Color palette

${PALETTE.map(([token, hex, role]) => `- \`${token}\` ${hex} — ${role}`).join('\n')}

## Action labels (tactical, single source of truth: \`domain/actions.ts\`)

${ACTION_ORDER.map((k: ActionKey) => {
    const d = ACTIONS[k];
    return `- **${d.longLabel}** — ${d.label} · color \`var(${d.cssVar})\` · tone \`${d.tone}\``;
  }).join('\n')}

## Core labels (index funds only)

${CORE_ACTION_ORDER.map((k: CoreActionKey) => {
    const d = CORE_ACTIONS[k];
    return `- **${d.longLabel}** — ${d.label} · tone \`${d.tone}\``;
  }).join('\n')}

---

## Layout

- Slim header: A.R.G.U.S. + tagline on left; "Next event" chip + "Market Open" + "Updated {timeAgo}" on right (e.g., "Updated 15m ago", "Updated 2h ago", "Updated just now")
- Sidebar (168 px): "Today's call" pill at top, 6 routes, version stamp at bottom — pill behavior is STABLE across pages (does not dim or change on the Today page)
- Main: scrollable padded content
- Mobile (< 720 px): sidebar collapses to a 56 px dot rail; the "Today's call" pill stays visible

## Routes

${ROUTES.map(([name, desc]) => `- **${name}** — ${desc}`).join('\n')}

## Persistent state visible across every page

- Today's call pill (sidebar top) — consistent, never page-specific
- Next critical event chip with impact-colored dot (header right)
- Version stamp (sidebar bottom, header pill)

---

## Current data state

LIVE: FRED rates/VIX (+ HY OAS), J-Quants Japan watchlist, Twelve Data US watchlist, CoinGecko crypto watchlist (keyless), Event Radar (official calendars + Treasury auctions), Action Label Engine v0 (rule-based), Corporate Catalysts (SEC EDGAR + Finnhub + J-Quants), Market Regime / Capital Rotation v1 (rule-based ETF/HY-OAS proxy scoring, regime-v1), the live-composed Today hero (action-labels + market-regime + events; no hand-written judgment), and the manual GPT-5.5 Pro Handoff export. Also live: Entry Scout (per-stock 瞬間診断 with Flow Intelligence + 日証金/JPX short + a calibrated one-line call/narrative), the self-scoring Prediction/Scout/Close-Pin ledgers, and daily automated AI judgment (GPT-5.5 + Gemini, recorded second opinion — runs via the prediction-ledger cron when the admin token is set, 30-min cache between runs). Action Alerts v1 is LIVE/partial (fetches /api/argus/action-alerts — JP/US equities, GLD, TLT, XLRE, crypto, USD/JPY, cash, core funds) with an explicit mock fallback on failure; Evidence-First event/dossier integration is now ON the dedicated page too (v10.45). Also live: the 24/7 Event Backbone (market-session Gear 0/1, deterministic — S高/急変/flow), /api/argus/events-active, the Today Event Intelligence card, and the deterministic Research Dossier v1 (no LLM). Event-state limitations: in-memory (no durable Event Ledger yet), market-session detection only, no PTS/L2/tape/VWAP, no Gear 2/3 Dynamic Workflows. Market Regime uses ETF/index proxies, not direct capital flow. NOT trading advice — decision support only.

## Decisions log

**Kept:**
${KEPT.map((s) => `- ${s}`).join('\n')}

**Replaced:**
${REPLACED.map((s) => `- ${s}`).join('\n')}

**Dropped:**
${DROPPED.map((s) => `- ${s}`).join('\n')}

---

## Open questions for review

${OPEN_QUESTIONS.map((q, i) => `${i + 1}. ${q}`).join('\n')}

## Known gaps

${GAPS.map((s) => `- ${s}`).join('\n')}
`;
}

export const AIReview: React.FC = () => {
  const [copied, setCopied] = useState(false);
  const [backedUp, setBackedUp] = useState<null | number>(null);
  const [manifest, setManifest] = useState<any>(null);
  const version = __APP_VERSION__;

  // Live runtime manifest (v10.107): the AI Review Sheet's static prose can drift,
  // so we LEAD with the real runtime state and also fold it into the copied
  // markdown — external AIs then reason from current facts, not a stale doc.
  React.useEffect(() => {
    const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;
    if (!backend) return;
    let alive = true;
    fetch(backend.replace(/\/$/, '') + '/api/argus/runtime-manifest')
      .then((r) => r.json()).then((d) => { if (alive) setManifest(d); })
      .catch(() => { /* static doc still renders */ });
    return () => { alive = false; };
  }, []);

  const handleCopy = async () => {
    // v11.8.0: append the device-local Position/Exposure summary (clipboard only).
    const pe = latestExposure();
    const md = buildMarkdown(version, manifest)
      + '\n\n' + (pe ? exposureSummaryText(pe)
        : '## Position / Exposure Summary (device-local)\n実保有サマリ: 未計算(TodayまたはWatchlistを開くと計算されます)。')
      + '\n' + backupStatusTextJa()
      + '\n\n' + dqHandoffTextJa()
      + '\n\n' + apHandoffTextJa(latestActionPriorities())
      + '\n\n' + sbHandoffTextJa(latestSessionBrief())
      + '\n\n' + scHandoffTextJa(latestScenarios())
      + '\n\n' + ntHandoffTextJa()
      + '\n\n' + lrHandoffTextJa();
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      const w = window.open('', '_blank');
      if (w) {
        w.document.body.style.fontFamily = 'monospace';
        w.document.body.style.whiteSpace = 'pre-wrap';
        w.document.body.textContent = md;
      }
    }
  };

  const handleBackup = () => {
    const n = downloadBackup(false);          // argus-backup-<date>.json
    setBackedUp(n);
    setTimeout(() => setBackedUp(null), 2600);
  };

  return (
    <article className="review">
      <h1>A.R.G.U.S. — AI Review Sheet</h1>
      <p className="review__tagline">
        Self-contained snapshot for ChatGPT / LLM evaluation. Paste into a chat
        or share the URL.
      </p>

      <div className="review__toolbar">
        <button
          className={`review__copy ${copied ? 'is-copied' : ''}`}
          onClick={handleCopy}
        >
          {copied ? '✓ コピー済み' : '📋 アプリ仕様をコピー(レビュー用)'}
        </button>
        <button
          className={`review__copy ${backedUp != null ? 'is-copied' : ''}`}
          onClick={handleBackup}
          title="保有・売買ジャーナル・リサーチメモ・判断ログを1つのJSONとして端末にDL"
        >
          {backedUp != null ? (backedUp > 0 ? `✓ ${backedUp}件DL` : '保存対象なし') : '💾 評価用バックアップをDL'}
        </button>
        <span className="review__meta">
          v{version} · live at <code>mitsugue.github.io/argus/</code>
        </span>
      </div>

      {/* RUNTIME (live) — current state so the static sections below never mislead
          an external AI. Generated from /api/argus/runtime-manifest (v10.107). */}
      {manifest && (
        <div className="review__runtime">
          <div className="review__runtime-head">RUNTIME — live state（下の静的な記述より優先）</div>
          <table className="review__table">
            <tbody>
              <tr><td className="dim">Build / asOf</td><td><code>{manifest.buildSha ?? '—'}</code> · {manifest.asOf?.slice(0, 16).replace('T', ' ')}Z</td></tr>
              <tr><td className="dim">Routes (5)</td><td>{(manifest.activeRoutes || []).join(' · ')}</td></tr>
              <tr><td className="dim">Providers</td><td>{manifest.providers?.confirmedLive}/{manifest.providers?.total} live{(manifest.providers?.degraded || []).length ? ` · degraded: ${(manifest.providers.degraded).join(', ')}` : ''}</td></tr>
              <tr><td className="dim">Calibration</td><td>{manifest.calibration?.phase}</td></tr>
              <tr><td className="dim">Downside</td><td>active {manifest.downside?.activeIncidents} · JP {manifest.downside?.jpIntradayOverlay} · holder {manifest.downside?.holderRiskOverlay}</td></tr>
              <tr><td className="dim">TDnet</td><td>{manifest.tdnet?.status}{manifest.tdnet?.count ? ` (${manifest.tdnet.count})` : ''} · {manifest.tdnet?.provider}</td></tr>
              <tr><td className="dim">Layer 2B</td><td>configured={String(manifest.ownerWatchlist?.layer2bConfigured)} — {manifest.ownerWatchlist?.note}</td></tr>
              <tr><td className="dim">Decision Value</td><td>{manifest.decisionValue?.phase}</td></tr>
              <tr><td className="dim">Visibility</td><td>{manifest.visibility?.visibilityLevel ?? '—'}{manifest.visibility?.confidenceCap != null ? ` · cap ${manifest.visibility.confidenceCap}` : ''}{(manifest.visibility?.reasonCodes || []).length ? ` · ${(manifest.visibility.reasonCodes).slice(0, 6).join(', ')}` : ''}</td></tr>
              <tr><td className="dim">AI</td><td>{manifest.ai?.status} · {manifest.ai?.note}</td></tr>
              <tr><td className="dim">Safety</td><td>{(manifest.safetyBoundaries || []).join('; ')}</td></tr>
            </tbody>
          </table>
          <ul className="review__runtime-limits">
            {(manifest.currentLimitations || []).map((x: string, i: number) => <li key={i}>{x}</li>)}
          </ul>
        </div>
      )}

      {/* What each AI tool exposes — the user kept asking "それぞれ何が違うのか". */}
      <div className="review__toolnote">
        <b>AI連携ツールの違い:</b>
        <ul>
          <li><b>📋 アプリ仕様(このボタン)</b> — ARGUS自体の機能・設計・既知の穴をMarkdownで出力。「アプリをレビューして」とLLMに渡す<em>開発レビュー用</em>。投資判断データは入りません。</li>
          <li><b>🧠 AI相談(各銘柄)</b> — 個別銘柄の入り判断。フロー・信用需給・ARGUS校正を先頭に置いたモート起点プロンプト。<em>エントリー用</em>。</li>
          <li><b>Copy for GPT(Watchlist下部)</b> — 今の地合い+ウォッチリスト全体のスナップショット。<em>全体相談用</em>。</li>
          <li><b>💾 バックアップ</b> — {BACKUP_KEYS.length}種の端末データ(保有/売買/メモ/ログ)をJSONでDL。クラウド同期とは別の手動コピー。</li>
        </ul>
      </div>

      <h2>Identity</h2>
      <p>
        A.R.G.U.S. = <em>Autonomous Risk and Global Uncertainty Scanner</em>. A
        personal action-decision engine for daily investing. Not a chart app.
        Not a visual toy. <strong>A calm investment command center that classifies
        market conditions into action categories, with market visuals serving as
        evidence rather than spectacle.</strong>
      </p>
      <p>
        The app must answer, within 10 seconds: what is today's call, what is
        the risk, why, which assets to touch, which to avoid, what to wait for
        next — and what would change the current posture.
      </p>

      <h2>Primary product shift (v8)</h2>
      <p>
        v8 retires the old capital-flow visualization-first approach. The product
        center is now <strong>action judgment</strong>. Market visuals
        (<em>Regime Matrix</em>, <em>Capital Rotation Board</em>, <em>Top
        Rotations</em>) exist only to support decisions, not to become the
        main experience. The bubble / SectorBlob viz is retired from the main UI.
      </p>

      <h2>Market visuals rule</h2>
      <p>
        Market visuals must never become the primary experience. They should
        always answer one of three questions:
      </p>
      <ol>
        <li>Where is capital rotating?</li>
        <li>What regime are we in?</li>
        <li>How does this support the current action labels?</li>
      </ol>
      <p>
        Visuals are <strong>supporting evidence, not trading signals by
        themselves</strong>. This rule exists because older versions of
        A.R.G.U.S. were too focused on visualizing capital flow; v8.1 keeps
        visuals only as decision-support tools.
      </p>

      <h2>Design philosophy</h2>
      <ul>
        <li>Bloomberg Terminal + Linear + Raycast + Stripe Dashboard — calm, precise, credible</li>
        <li>Dark navy, no HUD, no cyberpunk neon, no decorative crosshairs</li>
        <li>Single primary action visually dominant; everything else muted</li>
        <li><strong>Intentional bilingual structure.</strong> English chrome for system clarity; Japanese content for market commentary, news, scanner rationale, and user-facing investment reasoning. This mix is by design — not a transition mistake.</li>
        <li>10-second rule for the daily call</li>
      </ul>

      <h2>Color palette</h2>
      <table className="review__table">
        <thead>
          <tr>
            <th style={{ width: 200 }}>Token</th>
            <th>Hex</th>
            <th>Role</th>
          </tr>
        </thead>
        <tbody>
          {PALETTE.map(([token, hex, role]) => (
            <tr key={token}>
              <td><code>{token}</code></td>
              <td>
                <span className="review__swatch">
                  <span className="review__swatch-chip" style={{ background: hex }} />
                  <span className="review__swatch-hex">{hex}</span>
                </span>
              </td>
              <td className="dim">{role}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Action label system</h2>
      <p className="dim">Single source of truth: <code>web/src/domain/actions.ts</code>. Tactical labels (everything except index funds):</p>
      <table className="review__table">
        <thead>
          <tr>
            <th style={{ width: 220 }}>Pill</th>
            <th>Long label</th>
            <th>Tone</th>
          </tr>
        </thead>
        <tbody>
          {ACTION_ORDER.map((k: ActionKey) => {
            const d = ACTIONS[k];
            return (
              <tr key={k}>
                <td>
                  <span className="review__action-row">
                    <ActionPill action={k} />
                  </span>
                </td>
                <td>{d.longLabel}</td>
                <td className="dim">{d.tone}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <p className="dim" style={{ marginTop: 20 }}>Core labels (index funds only):</p>
      <table className="review__table">
        <thead>
          <tr>
            <th style={{ width: 220 }}>Pill</th>
            <th>Long label</th>
            <th>Tone</th>
          </tr>
        </thead>
        <tbody>
          {CORE_ACTION_ORDER.map((k: CoreActionKey) => {
            const d = CORE_ACTIONS[k];
            return (
              <tr key={k}>
                <td>
                  <span className="review__action-row">
                    <ActionPill action={k} />
                  </span>
                </td>
                <td>{d.longLabel}</td>
                <td className="dim">{d.tone}</td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <h2>Layout</h2>
      <ul>
        <li><strong>Header (slim, 14 px padding).</strong> Brand A.R.G.U.S. + tagline on left. Next-event chip with impact-colored dot, "Market Open", and "Updated {'{timeAgo}'}" on right (rendered as e.g., "Updated 15m ago", "Updated 2h ago", "Updated just now" — never the literal placeholder).</li>
        <li><strong>Sidebar (168 px).</strong> "Today's call" pill at top — STABLE across pages (does not dim or change). Six route buttons. Version stamp at bottom.</li>
        <li><strong>Main.</strong> Scrollable padded content area.</li>
        <li><strong>Mobile (&lt; 720 px).</strong> Sidebar collapses to a 64 px dot rail; "Today's call" pill stays visible; "Market Open" + "Updated" hidden; brand version pill, next event chip, AI review link in footer stay.</li>
      </ul>

      <h2>Routes</h2>
      <ol>
        {ROUTES.map(([name, desc]) => (
          <li key={name}><strong>{name}</strong> — {desc}</li>
        ))}
      </ol>

      <h2>Persistent always-visible state</h2>
      <ol>
        <li>Today's call pill in sidebar top (the answer to "what is today's call?") — consistent across every page, never page-specific</li>
        <li>Next critical event chip in header right (the answer to "what should I wait for next?")</li>
        <li>Version stamp at sidebar bottom and header brand pill (build provenance)</li>
      </ol>

      <h2>Market Regime structure (v8.1)</h2>
      <ol>
        <li><strong>Capital Rotation Board (primary).</strong> Three signals per asset class — flow direction (meter + label), strength (Low / Medium / High), role (Risk / Defensive / Hedge / Duration / Liquidity). No action labels — those live on Action Alerts / Watchlist so this view stays a pure flow diagnostic.</li>
        <li><strong>Regime Matrix (supporting).</strong> Compact 2-axis chart: Growth ↔ Defensive (x) × Risk ↔ Duration (y), driven by live regime-v1 axes. Current location dot + rotation-group context dots. Smaller than v8.0.</li>
        <li><strong>Regime Summary.</strong> Short bilingual paragraph — English headline + JP commentary.</li>
        <li><strong>Regime Glossary.</strong> Ten regime tags with Japanese definitions.</li>
      </ol>

      <h2>Current data state</h2>
      <p>LIVE: FRED rates/VIX (+ HY OAS), J-Quants Japan watchlist, Twelve Data US watchlist, CoinGecko crypto watchlist (keyless), Event Radar, Action Label Engine v0 (rule-based), Corporate Catalysts, Market Regime / Capital Rotation v1 (rule-based ETF/HY-OAS proxy scoring), the live-composed Today hero (action-labels + market-regime + events), and the manual GPT-5.5 Pro Handoff. Also live: Entry Scout (per-stock 瞬間診断 with Flow Intelligence + 日証金/JPX short + a calibrated one-line call/narrative), the self-scoring Prediction/Scout/Close-Pin ledgers, and daily automated AI judgment (GPT-5.5 + Gemini, recorded second opinion — runs via the prediction-ledger cron when the admin token is set, 30-min cache between runs). Action Alerts v1 is LIVE/partial (fetches /api/argus/action-alerts — JP/US equities, GLD, TLT, XLRE, crypto, USD/JPY, cash, core funds) with an explicit mock fallback on failure; Evidence-First event/dossier integration is now ON the dedicated page too (v10.45). Also live: the 24/7 Event Backbone (market-session Gear 0/1, deterministic — S高/急変/flow), /api/argus/events-active, the Today Event Intelligence card, and the deterministic Research Dossier v1 (no LLM). Event-state limitations: in-memory (no durable Event Ledger yet), market-session detection only, no PTS/L2/tape/VWAP, no Gear 2/3 Dynamic Workflows. Market Regime uses ETF/index proxies, not direct capital flow. NOT trading advice — decision support only.</p>

      <h2>Decisions log</h2>
      <div className="review__columns">
        <div className="review__panel">
          <div className="review__panel-title">Kept</div>
          <ul>
            {KEPT.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
        <div className="review__panel">
          <div className="review__panel-title">Replaced</div>
          <ul>
            {REPLACED.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
      </div>
      <div className="review__panel" style={{ marginTop: 8 }}>
        <div className="review__panel-title">Dropped</div>
        <ul>
          {DROPPED.map((s) => <li key={s}>{s}</li>)}
        </ul>
      </div>

      <h2>Open questions for review</h2>
      <ol>
        {OPEN_QUESTIONS.map((q) => <li key={q}>{q}</li>)}
      </ol>

      <h2>Known gaps (not yet built)</h2>
      <ul>
        {GAPS.map((s) => <li key={s}>{s}</li>)}
      </ul>
    </article>
  );
};
