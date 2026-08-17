import React from 'react';
import { ImportantEventsCard } from '../components/dashboard/ImportantEventsCard';
import { NotificationPanel } from '../components/NotificationPanel';
import { PageShell } from './PageShell';

export const NotificationsPage: React.FC = () => (
  <PageShell
    title="Notifications"
    subtitle="Primary Action、重要カタリスト、リスク条件の重大な変化だけを確認します。"
  >
    <NotificationPanel />
    <ImportantEventsCard />
  </PageShell>
);

export default NotificationsPage;
