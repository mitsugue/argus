import React, { useState } from 'react';
import { ActionPill } from '../components/action/ActionBadge';
import { ACTIONS, ACTION_ORDER, CORE_ACTIONS, CORE_ACTION_ORDER } from '../domain/actions';
import type { ActionKey, CoreActionKey } from '../types/action';
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
  ['--red',          '#F87171', 'EXIT / high risk'],
  ['--amber',        '#FBBF24', 'TRIM / medium risk'],
  ['--blue',         '#60A5FA', 'WAIT_FOR_PULLBACK'],
  ['--cyan',         '#22D3EE', 'BUY_DIP / GRADUAL_ADD'],
  ['--green',        '#34D399', 'ADD / CONTINUE / low risk'],
  ['--gray',         '#64748B', 'WAIT / WAIT_LUMP'],
];

const ROUTES = [
  ['Today',         'Daily Command Center — hero judgment + alerts grid + priority watchlist + events + core preview'],
  ['Action Alerts', '9 asset-class cards (8 satellites + index funds list)'],
  ['Market Regime', 'Active regime + bubble viz (subordinate supporting layer) + 10-tag glossary'],
  ['Event Radar',   'Upcoming events list + D-7 → D+1 escalation policy'],
  ['Watchlist',     'JP + US dense rows with action label, news, scanner reason; sorted by urgency'],
  ['Core Portfolio','Long-term index status with calm vocabulary'],
];

const KEPT = [
  'HudFrame → AppShell (slim header, no chrome)',
  'theme tokens (structure preserved, palette swapped)',
  'SectorBlob (now subordinate viz in Market Regime, not main)',
  'Backend scanner.py + argus_ledger.py (untouched, ready to wire)',
];

const DROPPED = [
  'Sticky Notes (investment focus over memos)',
  'HUD ornaments: clock, UPLINK MOCK pill, crosshairs',
  'Orbitron / Share Tech Mono / Michroma fonts',
  'Sci-fi letter-spacing (4px+) on body and headings',
  'Design-system-preview as the home page',
  '3D libs in DOM (R3F, globe.gl, force-graph-3d — still in deps but unused)',
];

const OPEN_QUESTIONS = [
  'Is the calm aesthetic carrying enough authority for serious investment use, or too muted?',
  'Watchlist row density: is JP/US dense-line right, or should rows expand on click for full data?',
  'Action vocabulary: are 7 tactical labels enough, or do we need sub-actions (e.g., "trim 1/3" vs "trim 1/2")?',
  'Cross-page navigation: enough handles (Today\'s call pill, Next event chip, section-head links), or missing connections?',
  'JP/EN mix: working as a transition mode, or confusing? Should there be a global EN-only toggle?',
  'Should asset-class display names (Japan Individual Stocks etc.) also be JP, or stay structural English?',
  'Is the Market Regime bubble useful as supporting layer, or does it still feel like a leftover from v5?',
];

const GAPS = [
  'Watchlist add/remove UI — currently mock-only, no input',
  'No detail panel when clicking an alert or watchlist row',
  'No filter chips on Watchlist (e.g., "show EXIT only")',
  'No real backend wiring — scanner.py exists, frontend not consuming',
  'No history / audit log for past judgments',
  'No tooltip explanations on hover for action labels',
  'No portfolio P&L / dollar exposure rendering',
];

function buildMarkdown(version: string): string {
  return `# A.R.G.U.S. — AI Review Sheet (v${version})

**Identity.** A.R.G.U.S. = Autonomous Risk and Global Uncertainty Scanner. Personal action-decision engine for daily investing. Not a chart app. Not a visual toy. Answers: what is today's call, what is the risk, why, what to touch, what to avoid, what to wait for next.

**Live URL.** https://mitsugue.github.io/stock-scanner/

---

## Design philosophy

- Bloomberg Terminal + Linear + Raycast + Stripe Dashboard
- Dark navy, calm, professional. No HUD, no cyberpunk, no neon glow
- No decorative crosshairs, no fake terminal chrome, no Orbitron brand
- Single primary action visually dominant; secondary state quiet
- 10-second rule: user understands today's call within 10 seconds of opening the app
- Bilingual content during user transition phase: English chrome, Japanese info content

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

- Slim header: A.R.G.U.S. + tagline on left; "Next event" chip + "Market Open" + "Updated Nh ago" on right
- Sidebar (168 px): "Today's call" pill at top, 6 routes, version stamp at bottom
- Main: scrollable padded content
- Mobile (< 720 px): sidebar collapses to a 56 px dot rail; the "Today's call" pill stays visible

## Routes

${ROUTES.map(([name, desc]) => `- **${name}** — ${desc}`).join('\n')}

## Persistent state visible across every page

- Today's call pill (sidebar top)
- Next critical event chip with impact-colored dot (header right)
- Version stamp (sidebar bottom)

---

## Mock data

Plausible "Tuesday before US CPI" snapshot. Conservative across satellites (Wait / Wait for Pullback / Trim), steady on core (Continue / Wait Lump / Gradual Add). NOT trading advice — the goal is to motivate the UI shapes, not to model real markets.

## Decisions log

**Kept:**
${KEPT.map((s) => `- ${s}`).join('\n')}

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
  const version = __APP_VERSION__;

  const handleCopy = async () => {
    const md = buildMarkdown(version);
    try {
      await navigator.clipboard.writeText(md);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard API not available (insecure context etc.) — fallback: open in new window for manual select.
      const w = window.open('', '_blank');
      if (w) {
        w.document.body.style.fontFamily = 'monospace';
        w.document.body.style.whiteSpace = 'pre-wrap';
        w.document.body.textContent = md;
      }
    }
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
          {copied ? '✓ Copied markdown' : 'Copy as markdown'}
        </button>
        <span className="review__meta">
          v{version} · live at <code>mitsugue.github.io/stock-scanner/</code>
        </span>
      </div>

      <h2>Identity</h2>
      <p>
        A.R.G.U.S. = <em>Autonomous Risk and Global Uncertainty Scanner</em>. A
        personal action-decision engine for daily investing. Not a chart app.
        Not a visual toy. The app must answer, within 10 seconds: what is today's
        call, what is the risk, why, which assets to touch, which to avoid, what
        to wait for next.
      </p>

      <h2>Design philosophy</h2>
      <ul>
        <li>Bloomberg Terminal + Linear + Raycast + Stripe Dashboard — calm, precise, credible</li>
        <li>Dark navy, no HUD, no cyberpunk neon, no decorative crosshairs</li>
        <li>Single primary action visually dominant; everything else muted</li>
        <li>Bilingual during transition: English chrome (labels, action keys, sections), Japanese info content (summary, reasons, news, scanner notes)</li>
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
        <li><strong>Header (slim, 14 px padding).</strong> Brand A.R.G.U.S. + tagline on left. Next-event chip with impact-colored dot, "Market Open", and "Updated Nh ago" on right.</li>
        <li><strong>Sidebar (168 px).</strong> "Today's call" pill at top (clickable, jumps to Command Center). Six route buttons. Version stamp at bottom.</li>
        <li><strong>Main.</strong> Scrollable padded content area.</li>
        <li><strong>Mobile (&lt; 720 px).</strong> Sidebar collapses to a 56 px dot rail; "Today's call" pill stays visible; "Market Open" + "Updated" hidden, brand + next event chip stay.</li>
      </ul>

      <h2>Routes</h2>
      <ol>
        {ROUTES.map(([name, desc]) => (
          <li key={name}><strong>{name}</strong> — {desc}</li>
        ))}
      </ol>

      <h2>Persistent always-visible state</h2>
      <ol>
        <li>Today's call pill in sidebar top (the answer to "what is today's call?")</li>
        <li>Next critical event chip in header right (the answer to "what should I wait for next?")</li>
        <li>Version stamp at sidebar bottom (build provenance)</li>
      </ol>

      <h2>Mock data</h2>
      <p>Plausible "Tuesday before US CPI" snapshot. Cautious across satellites, steady on core. NOT trading advice — the data motivates the UI shapes, not real markets.</p>

      <h2>Decisions log</h2>
      <div className="review__columns">
        <div className="review__panel">
          <div className="review__panel-title">Kept</div>
          <ul>
            {KEPT.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
        <div className="review__panel">
          <div className="review__panel-title">Dropped</div>
          <ul>
            {DROPPED.map((s) => <li key={s}>{s}</li>)}
          </ul>
        </div>
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
