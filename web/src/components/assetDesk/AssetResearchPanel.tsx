import React, { useState } from 'react';
import type { DeskCardData } from './types';
import { getNote, saveNote } from '../../lib/researchNotes';
import { OsintDeepDive } from '../dashboard/OsintDeepDive';
import { decisionHistoryFor } from '../../lib/decisionQuality';
import { pastPatternLineJa } from '../../lib/learningReview';

// Saved notes and formal ARGUS history remain available after consultation retirement.

export const AssetResearchPanel: React.FC<{
  d: DeskCardData;
  onRemove: (id: string) => void;
}> = ({ d, onRemove }) => {
  const [note, setNote] = useState(() => getNote(d.asset.symbol)?.text ?? '');
  const [noteSaved, setNoteSaved] = useState(false);
  const hist = decisionHistoryFor(d.asset.symbol, 2);
  return (
    <>
      <div className="asset-detail__note">
        <span className="asset-detail__k">📝 銘柄メモ（端末内に保存。保護には完全バックアップJSONを書き出してください）</span>
        <textarea
          className="asset-detail__note-area"
          value={note}
          placeholder="調べたことや次に確認したいことを保存…"
          onChange={(e) => { setNote(e.target.value); setNoteSaved(false); }}
          onBlur={() => { saveNote(d.asset.symbol, note); setNoteSaved(true); }}
        />
        {noteSaved && <span className="asset-detail__note-saved">✓ 保存</span>}
      </div>

      {/* v12.1.0: マルチエージェントOSINT(計画→収集→Gemini/GPT→検証→統合) */}
      <OsintDeepDive symbol={d.asset.symbol} market={d.asset.market} held={!!d.pn?.held} />

      {/* DECISION HISTORY (v11.11.0) — 端末内記録の答え合わせ */}
      {hist.length > 0 && (
        <div className="uac-sec">
          <div className="uac-sec-t">DECISION HISTORY</div>
          {(() => { const pl = pastPatternLineJa(d.asset.symbol);
            return pl ? <p className="uac-next" style={{ marginBottom: 2, color: 'var(--text-faint)' }}>{pl}</p> : null; })()}
          {hist.map((h) => (
            <p key={h.id} className="uac-next" style={{ marginBottom: 2 }}>
              <span style={{ color: 'var(--text-faint)' }}>{h.asOf.slice(0, 10)}</span>
              <span style={{ marginLeft: 5 }}>[{h.decisionContext}]</span>
              {h.outcome?.outcomeReturn5d != null && (
                <span style={{ marginLeft: 5, color: h.outcome.outcomeReturn5d >= 0 ? 'var(--value-positive)' : 'var(--value-negative)' }}>
                  5d {h.outcome.outcomeReturn5d >= 0 ? '+' : ''}{h.outcome.outcomeReturn5d.toFixed(1)}%
                </span>
              )}
              {h.outcome?.outcomeReadableJa && (
                <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>{h.outcome.outcomeReadableJa}</span>
              )}
              {!h.outcome?.outcomeReadableJa && <span style={{ marginLeft: 5, color: 'var(--text-faint)' }}>結果待ち</span>}
            </p>
          ))}
        </div>
      )}

      <p className="uac-next" style={{ margin: '6px 0 0' }}>
        <button className="asset-mini asset-mini--danger" aria-label={`Remove ${d.asset.symbol}`}
                onClick={() => onRemove(d.asset.id)}>Remove(登録解除)</button>
      </p>
    </>
  );
};
