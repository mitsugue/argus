/** Fetch states are attributed to their own reader, never to another feed. */
export function partialFeedReasonCodes(input: {
  actionLabels: string; marketRegime: string; eventRadar: string;
  jpQuotes: string; usQuotes: string; hasJpAssets: boolean; hasUsAssets: boolean;
}): string[] {
  return [
    input.actionLabels === 'partial' ? 'action_labels_partial' : null,
    input.marketRegime === 'partial' ? 'market_regime_partial' : null,
    input.eventRadar === 'partial' ? 'event_radar_partial' : null,
    (input.hasJpAssets && input.jpQuotes === 'partial')
      || (input.hasUsAssets && input.usQuotes === 'partial') ? 'watchlist_polling_partial' : null,
  ].filter((code): code is string => code !== null);
}
