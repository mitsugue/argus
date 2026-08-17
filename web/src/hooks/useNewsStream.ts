import { useEffect, useRef, useState } from 'react';
import type { GlobePillar, GlobePulse, NewsEvent, NewsSeverity } from '../types';
import { pickHeadline, uid } from '../mock/data';

const MAX_NEWS = 5;
const PULSE_TTL_MS = 1900;
const INTERVAL_MIN = 3200;
const INTERVAL_MAX = 5200;

const CYAN = '#00f3ff';
const AMBER = '#ffb700';

function severityOf(pillar: GlobePillar): NewsSeverity {
  // Amber/danger pillars or very high intensity → critical
  if (pillar.color === 'amber' || pillar.color === 'danger') return 'critical';
  if (pillar.intensity >= 0.85) return 'critical';
  return 'normal';
}

export function useNewsStream(pillars: GlobePillar[]) {
  const [events, setEvents] = useState<NewsEvent[]>([]);
  const [pulses, setPulses] = useState<GlobePulse[]>([]);
  // Keep latest pillars accessible to the timer closure without re-init
  const pillarsRef = useRef(pillars);
  pillarsRef.current = pillars;

  // Emit news events at a randomized cadence
  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | undefined;

    const emit = () => {
      if (cancelled) return;
      const all = pillarsRef.current;
      if (!all.length) {
        timeoutId = setTimeout(emit, 600);
        return;
      }
      const pillar = all[Math.floor(Math.random() * all.length)];
      const severity = severityOf(pillar);
      const color = severity === 'critical' ? AMBER : CYAN;
      const now = Date.now();

      const event: NewsEvent = {
        id: uid('evt'),
        pillarId: pillar.id,
        lat: pillar.lat,
        lng: pillar.lng,
        country: pillar.country,
        countryCode: pillar.countryCode,
        source: pillar.source,
        headline: pickHeadline(pillar.id, pillar.headline),
        severity,
        receivedAt: now,
      };

      // 1. Globe pillar pulses immediately
      setPulses((prev) => [
        ...prev,
        {
          id: event.id,
          pillarId: pillar.id,
          lat: pillar.lat,
          lng: pillar.lng,
          color,
          bornAt: now,
          ttl: PULSE_TTL_MS,
        },
      ]);
      // 2. After a short beat, the news item slides into the frame
      //    — visually implies "data was beamed from globe to feed"
      setTimeout(() => {
        if (cancelled) return;
        setEvents((prev) => [event, ...prev].slice(0, MAX_NEWS));
      }, 320);

      const delay = INTERVAL_MIN + Math.random() * (INTERVAL_MAX - INTERVAL_MIN);
      timeoutId = setTimeout(emit, delay);
    };

    // First emission shortly after mount so the UI isn't blank
    timeoutId = setTimeout(emit, 250);

    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, []);

  // Expire pulses
  useEffect(() => {
    if (!pulses.length) return;
    const t = setInterval(() => {
      const now = Date.now();
      setPulses((prev) => prev.filter((p) => p.bornAt + p.ttl > now));
    }, 350);
    return () => clearInterval(t);
  }, [pulses.length]);

  return { events, pulses };
}
