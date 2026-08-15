import React from 'react';
import { ImportantEventsCard } from '../components/dashboard/ImportantEventsCard';
import { NotificationPanel } from '../components/NotificationPanel';
import type { RouteKey } from '../navigation';
import { PageShell } from './PageShell';

interface Props { onNavigate: (key: RouteKey) => void }

export const NotificationsPage: React.FC<Props> = ({ onNavigate }) => (
  <PageShell
    title="Notifications"
    subtitle="重要な変化、次のイベント、端末内の注意を一か所で確認します。"
  >
    <NotificationPanel />
    <ImportantEventsCard onNavigate={onNavigate} />
  </PageShell>
);

export default NotificationsPage;
