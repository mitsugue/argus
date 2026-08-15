import React from 'react';
import { setLocale, useLocale } from '../i18n';
import type { SettingsSection } from '../navigation';
import { BackupSettingsPanel } from './BackupPage';
import { PublicDiagnosticsPanel } from './DataQualityPage';
import { PageShell } from './PageShell';

interface Props { settingsSection?: SettingsSection }

const scrollToSection = (section: SettingsSection) => {
  const id = section === 'recovery' ? 'settings-recovery'
    : section === 'help' ? 'settings-help' : 'settings-status';
  window.requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: 'start' }));
};

export const Settings: React.FC<Props> = ({ settingsSection = 'status' }) => {
  const locale = useLocale();
  React.useEffect(() => { scrollToSection(settingsSection); }, [settingsSection]);

  return (
    <PageShell
      title="Settings"
      subtitle="言語、公開ステータス、バックアップと復元を管理します。"
    >
      <section className="card" aria-label="Language settings">
        <div className="section-head">
          <span className="section-head__title">LANGUAGE</span>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {(['en', 'ja'] as const).map((value) => (
            <button key={value} type="button" onClick={() => setLocale(value)}
              aria-pressed={locale === value}>
              {value === 'en' ? 'English' : '日本語'}
            </button>
          ))}
          <span className="cmd-alloc__note">設定はこの端末に保存されます。</span>
        </div>
      </section>

      <PublicDiagnosticsPanel />
      <BackupSettingsPanel initiallyOpen={settingsSection === 'recovery'} />

      <section id="settings-help" className="card" aria-label="Help">
        <div className="section-head">
          <span className="section-head__title">HELP</span>
        </div>
        <p className="cmd-alloc__note">
          Todayで今日の姿勢、Holdings / Watchlistで保有と銘柄詳細、Notificationsで変化と重要イベントを確認します。
          銘柄の行を開くとDecision / Chart / Evidence / Positionの順で詳細を確認できます。
        </p>
        <p className="cmd-alloc__note">
          公開画面は読み取り専用です。調査・翻訳・AI実行・本番運用の操作は、認証された運用経路だけで行います。
        </p>
      </section>
    </PageShell>
  );
};

export default Settings;
