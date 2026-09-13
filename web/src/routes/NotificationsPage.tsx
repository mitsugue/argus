import React from 'react';
import { JapanSqCalendarCard } from '../components/dashboard/JapanSqCalendarCard';
import { ImportantEventsCard } from '../components/dashboard/ImportantEventsCard';
import { NotificationPanel } from '../components/NotificationPanel';
import { NewsAlertsPanel } from '../components/notifications/NewsAlertsPanel';
import { PageShell } from './PageShell';

// v13.5.60 (owner iPhone review 2026-09-07): the third page is organised as
// three named sections — ニュース・市場リスク / 銘柄・判断の変化 / イベント —
// each with a stable anchor so a tap on Today lands on the matching section.
export const ALERTS_SECTION_IDS = {
  news: 'news-intel',
  assets: 'asset-alerts',
  events: 'important-events',
} as const;

export const NotificationsPage: React.FC = () => {
  React.useEffect(() => {
    let observer: MutationObserver | undefined;
    const focus = () => {
      const match = /^#notifications\/news\/([A-Za-z0-9:_-]{1,150})$/.exec(window.location.hash);
      const element = match && document.getElementById('news-'+match[1]);
      if (element) { element.scrollIntoView({block:'start'}); observer?.disconnect(); return true; }
      return false;
    };
    const start = () => { observer?.disconnect(); if (!focus()) {
      observer = new MutationObserver(focus); observer.observe(document.body,{childList:true,subtree:true});
    }};
    start(); window.addEventListener('hashchange',start);
    return () => { observer?.disconnect(); window.removeEventListener('hashchange',start); };
  }, []);
  return (
  <PageShell
    title="Notifications"
    subtitle="重大ニュース・市場リスク、銘柄と判断の変化、経済イベントを確認します。"
  >
    <NewsAlertsPanel />
    <NotificationPanel />
    <JapanSqCalendarCard />
    <ImportantEventsCard />
  </PageShell>
);
};

export default NotificationsPage;
