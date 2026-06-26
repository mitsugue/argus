// Japanese labels for the risk-overlay enums (v10.161). These are status INFO that
// must communicate, so they read in Japanese — not raw RISK_OFF_WATCH / NORMAL.
// (Signal names like EXIT/PAUSE stay English by policy; these are not signals.)

export const jpIntradayJa = (v?: string | null): string =>
  (({ NORMAL: '平常', CAUTION: '警戒', RISK_OFF_WATCH: 'リスクオフ警戒' } as Record<string, string>)[v ?? '']
    ?? (v ? v.replace(/_/g, ' ') : ''));

export const globalRegimeJa = (v?: string | null): string =>
  (({
    RISK_ON: 'リスクオン', RISK_OFF: 'リスクオフ', NEUTRAL: '中立',
    EVENT_WAIT: 'イベント待ち', RISK_OFF_WATCH: 'リスクオフ警戒', CAUTION: '警戒',
  } as Record<string, string>)[v ?? ''] ?? (v ? v.replace(/_/g, ' ') : ''));
