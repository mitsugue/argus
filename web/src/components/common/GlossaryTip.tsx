// v13.5.36 — tap-to-explain for domain vocabulary (owner: 「言葉の意味が
// わからない」). DISPLAY ONLY: inline expansion (no overlay stacking, no
// hover dependency, no layout portal); zero authority over any decision.
import React from 'react';

import { glossaryEntry } from '../../domain/glossary';

export const GlossaryTip: React.FC<{
  glossaryKey: string;
  children: React.ReactNode;
}> = ({ glossaryKey, children }) => {
  const [open, setOpen] = React.useState(false);
  const entry = glossaryEntry(glossaryKey);
  if (!entry) return <>{children}</>;
  return <span className="glossary-tip" data-glossary-key={glossaryKey}>
    <button type="button" className="glossary-tip__term"
      aria-expanded={open}
      aria-label={`${entry.term}の説明を${open ? '閉じる' : '表示'}`}
      onClick={() => setOpen((value) => !value)}>{children}</button>
    {open && <span className="glossary-tip__body" role="note">
      {entry.explanationJa}</span>}
  </span>;
};
