import React from 'react';
import { PageShell } from './PageShell';
import { ActionBadge } from '../components/action/ActionBadge';
import { ACTION_ORDER, CORE_ACTION_ORDER } from '../domain/actions';

// Phase 1 landing — shows the action-label design system so the user can
// see every label rendered with its color/icon/JP text. Real Daily
// Command Center content (judgment / reasons / events / assets) lands here
// in Phase 3.
export const CommandCenter: React.FC = () => {
  return (
    <PageShell crumb="01 · COMMAND" title="司令塔" subtitle="design system preview">
      <section>
        <h2 className="page__section-title">tactical actions — 個別株 / コモディティ / 為替</h2>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {ACTION_ORDER.map((a) => (
            <ActionBadge key={a} action={a} size="lg" showEn />
          ))}
        </div>
      </section>

      <section>
        <h2 className="page__section-title">core actions — 長期インデックス</h2>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10 }}>
          {CORE_ACTION_ORDER.map((a) => (
            <ActionBadge key={a} action={a} size="lg" showEn />
          ))}
        </div>
      </section>

      <section>
        <h2 className="page__section-title">三サイズ</h2>
        <div style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
          <ActionBadge action="ESCAPE" size="sm" />
          <ActionBadge action="ESCAPE" size="md" />
          <ActionBadge action="ESCAPE" size="lg" />
        </div>
      </section>

      <p style={{ color: 'var(--hud-text-faint)', fontSize: 11, lineHeight: 1.7, marginTop: 12 }}>
        この上に Phase 3 で daily judgment(今日の総合判断・リスク・主要理由3点・今日触らないアセット・1文サマリー)を載せる。<br />
        色/アイコン/JP ラベルは <code style={{ color: 'var(--hud-cyan)' }}>web/src/domain/actions.ts</code> の単一ソースから供給。
      </p>
    </PageShell>
  );
};
