import React from 'react';
import './PageShell.css';

interface Props {
  crumb?: string;
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}

export const PageShell: React.FC<Props> = ({ crumb, title, subtitle, children }) => (
  <section className="page">
    <header className="page__head">
      {crumb && <span className="page__crumb">{crumb}</span>}
      <h1 className="page__title">{title}</h1>
      {subtitle && <span className="page__subtitle">{subtitle}</span>}
    </header>
    {children}
  </section>
);

// Stand-in for routes whose own page isn't filled out yet. Calm card,
// not a giant "実装予定" debug screen.
export const Placeholder: React.FC<{ title: string; note?: string }> = ({ title, note }) => (
  <div className="page__empty">
    <div className="page__empty-title">{title}</div>
    {note && <div className="page__empty-note">{note}</div>}
  </div>
);
