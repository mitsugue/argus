import React, { useState } from 'react';
import { latestExposure } from '../../lib/positionExposureShare';
import { exposureSummaryText } from '../../domain/positionExposure';
import { backupStatusTextJa } from '../../lib/portfolioSync';
import { dqHandoffTextJa } from '../../lib/decisionQuality';
import { latestActionPriorities } from '../../lib/positionExposureShare';
import { apHandoffTextJa } from '../../domain/actionPriority';
import { sbHandoffTextJa } from '../../domain/sessionBrief';
import { latestSessionBrief } from '../../lib/positionExposureShare';
import { ntHandoffTextJa } from '../../lib/notifications';
import { lrHandoffTextJa } from '../../lib/learningReview';

// "Copy for GPT-5.5 Pro" — utility action. On click it fetches the backend
// /api/argus/pro-handoff (no admin token, no secrets, no OpenAI/Gemini call) and
// copies the ready-to-paste prompt to the clipboard. Falls back to a selectable
// textarea if the Clipboard API is unavailable. It never auto-opens ChatGPT.

type S = 'idle' | 'loading' | 'copied' | 'manual' | 'error';

export const ProHandoffButton: React.FC = () => {
  const [state, setState] = useState<S>('idle');
  const [text, setText] = useState('');
  const backend = import.meta.env.VITE_ARGUS_BACKEND_URL;

  async function onClick() {
    if (!backend) {
      setState('error');
      return;
    }
    setState('loading');
    try {
      const r = await fetch(backend.replace(/\/$/, '') + '/api/argus/pro-handoff');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      // v11.8.0: the server prompt is watchlist-level only (it never knows real
      // holdings). Append the device-local Position/Exposure summary here — it
      // goes ONLY to the clipboard the owner pastes themselves.
      const pe = latestExposure();
      const local = pe ? exposureSummaryText(pe)
        : '## Position / Exposure Summary (device-local)\n実保有サマリ: 未計算(TodayまたはWatchlistを開くと計算されます)。';
      const prompt: string = `${d.promptText || ''}\n\n${local}\n${backupStatusTextJa()}\n\n${dqHandoffTextJa()}\n\n${apHandoffTextJa(latestActionPriorities())}\n\n${sbHandoffTextJa(latestSessionBrief())}\n\n${ntHandoffTextJa()}\n\n${lrHandoffTextJa()}`;
      setText(prompt);
      try {
        await navigator.clipboard.writeText(prompt);
        setState('copied');
        window.setTimeout(() => setState('idle'), 2500);
      } catch {
        setState('manual'); // clipboard blocked → show selectable textarea
      }
    } catch {
      setState('error');
      window.setTimeout(() => setState('idle'), 2500);
    }
  }

  const label =
    state === 'loading' ? '準備中…'
      : state === 'copied' ? '✓ コピー済み(全体)'
      : state === 'error' ? 'unavailable'
      : '🧠 全体をAIに相談(地合い+保有)';

  return (
    <div className="pro-handoff">
      <button className="pro-handoff__btn" onClick={onClick} disabled={state === 'loading'}
              title="今の地合い+ウォッチリスト全体のスナップショットをLLMに渡すプロンプトをコピー(個別銘柄は各行の🧠 AI相談)">
        {label}
      </button>
      {state === 'manual' && (
        <div className="pro-handoff__manual">
          <div className="pro-handoff__hint">クリップボードが使えませんでした。下を選択して手動でコピーしてください。</div>
          <textarea
            className="pro-handoff__text"
            readOnly
            value={text}
            onFocus={(e) => e.currentTarget.select()}
          />
        </div>
      )}
    </div>
  );
};
