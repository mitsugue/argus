import React from 'react';
import './PageShell.css';

interface Props {
  crumb?: string;
  title: string;
  subtitle?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}

export const PageShell: React.FC<Props> = ({ crumb, title, subtitle, className, children }) => (
  <section className={className ? `page ${className}` : 'page'}>
    <header className="page__head">
      {crumb && <span className="page__crumb">{crumb}</span>}
      <h1 className="page__title">{title}</h1>
      {subtitle && <span className="page__subtitle">{subtitle}</span>}
      {title !== 'Settings' && <a className="page__guide-link"
        href="#settings/help">Help / Settings</a>}
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
