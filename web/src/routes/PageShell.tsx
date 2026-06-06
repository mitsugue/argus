import React from 'react';
import './PageShell.css';

interface Props {
  crumb: string;       // section code e.g. "01 · COMMAND"
  title: string;       // JP heading
  subtitle?: string;   // small right-aligned meta
  children: React.ReactNode;
}

export const PageShell: React.FC<Props> = ({ crumb, title, subtitle, children }) => (
  <section className="page">
    <header className="page__head">
      <span className="page__crumb">{crumb}</span>
      <h1 className="page__title">{title}</h1>
      {subtitle && <span className="page__subtitle">{subtitle}</span>}
    </header>
    {children}
  </section>
);

// Stand-in for routes that aren't built yet. Will be replaced one-by-one
// in the next phases.
export const Placeholder: React.FC<{ note?: string }> = ({ note }) => (
  <div className="page__empty">
    <div className="page__empty-mark">◌</div>
    <div>実装予定</div>
    {note && <div style={{ letterSpacing: '0.1em', fontSize: 10, marginTop: 6 }}>{note}</div>}
  </div>
);
