import React from 'react';
import { setLocale, useLocale } from '../i18n';
import type { SettingsSection } from '../navigation';
import { BackupSettingsPanel } from './BackupPage';
import { NewsIntakePanel } from '../components/settings/NewsIntakePanel';
import { WebPushPanel } from '../components/settings/WebPushPanel';
import { AiUsagePanel } from '../components/settings/AiUsagePanel';
import { OwnerIdentityPanel } from '../components/settings/OwnerIdentityPanel';
import { NotificationPanel } from '../components/NotificationPanel';
import { PublicDiagnosticsPanel } from './DataQualityPage';
import { PageShell } from './PageShell';
import {
  notificationPreferences, saveNotificationPreferences,
  type NotificationPreferences,
} from '../lib/notifications';

interface Props { settingsSection?: SettingsSection }

const scrollToSection = (section: SettingsSection) => {
  const id = section === 'recovery' ? 'settings-recovery'
    : section === 'help' ? 'settings-help' : 'settings-status';
  window.requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: 'start' }));
};

export const Settings: React.FC<Props> = ({ settingsSection = 'status' }) => {
  const locale = useLocale();
  const [notificationPrefs, setNotificationPrefs] = React.useState<NotificationPreferences>(
    () => notificationPreferences());
  const [notificationHistoryOpen, setNotificationHistoryOpen] = React.useState(false);
  React.useEffect(() => { scrollToSection(settingsSection); }, [settingsSection]);
  const toggleNotification = (key: keyof NotificationPreferences) => {
    const next = { ...notificationPrefs, [key]: !notificationPrefs[key] };
    setNotificationPrefs(next);
    saveNotificationPreferences(next);
  };

  return (
    <PageShell title="Settings">
      <OwnerIdentityPanel />
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
        </div>
      </section>

      <section className="card" aria-label="Notification settings">
        <div className="section-head">
          <span className="section-head__title">MATERIAL NOTIFICATIONS</span>
        </div>
        <div style={{ display: 'grid', gap: 7 }}>
          {([
            ['action', 'Primary Action・目標'],
            ['catalyst', '重要イベント'],
            ['risk', '保有リスク・無効化'],
            ['authority', '判断権限の喪失'],
            ['recovery', 'バックアップ・復元'],
          ] as const).map(([key, label]) => <label key={key}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
            <span>{label}</span>
            <input type="checkbox" checked={notificationPrefs[key]}
              onChange={() => toggleNotification(key)} />
          </label>)}
        </div>
      </section>

      <WebPushPanel />
      <details className="card" onToggle={(event) =>
        setNotificationHistoryOpen(event.currentTarget.open)}>
        <summary>端末内の通知履歴</summary>
        {notificationHistoryOpen && <NotificationPanel />}
      </details>
      <NewsIntakePanel />
      <AiUsagePanel />
      <PublicDiagnosticsPanel />
      <BackupSettingsPanel initiallyOpen={settingsSection === 'recovery'} />

      <section id="settings-help" className="card" aria-label="Help">
        <div className="section-head">
          <span className="section-head__title">HELP</span>
        </div>
        <p className="cmd-alloc__note">Today: 今日の見立て · Watchlist: 登録銘柄 · 13M: 米国株の研究</p>
      </section>
    </PageShell>
  );
};

export default Settings;
