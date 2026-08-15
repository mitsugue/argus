import React from 'react';
import { ImportantEventsCard } from '../components/dashboard/ImportantEventsCard';
import { NotificationPanel } from '../components/NotificationPanel';
import { PageShell } from './PageShell';

export const NotificationsPage: React.FC = () => (
  <PageShell
    title="Notifications"
    subtitle="重要な変化、次のイベント、端末内の注意を一か所で確認します。"
  >
    <NotificationPanel />
    <ImportantEventsCard />
  </PageShell>
);

export default NotificationsPage;
