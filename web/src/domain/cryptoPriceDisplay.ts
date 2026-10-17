import type { CryptoQuote, CryptoWatchlistSnapshot } from '../types/crypto';
import { cryptoQuoteDecisionUsable, exactAuthorityEpoch } from './liveAuthority';
import { coingeckoIdOf, SYMBOL_TO_COINGECKO } from '../lib/cryptoIds';
import type { AssetItem } from '../types/assetItem';

/** Price viewing only. Never an input to decisions, valuation or supply/demand. */
export interface CryptoDisplayQuote { quote: CryptoQuote; retained: boolean }
export type CryptoDisplayQuotes = Record<string, CryptoDisplayQuote>;

export function retainCryptoDisplay(quotes: CryptoDisplayQuotes): CryptoDisplayQuotes {
  return Object.fromEntries(Object.entries(quotes).map(([id, row]) =>
    [id, { quote: row.quote, retained: true }]));
}

/** Keep real prices on a partial/failed read; mock values cannot overwrite them. */
export function acceptCryptoDisplay(
  previous: CryptoDisplayQuotes, data: CryptoWatchlistSnapshot, ids: string[],
): CryptoDisplayQuotes {
  const next = retainCryptoDisplay(Object.fromEntries(Object.entries(previous)
    .filter(([id]) => ids.includes(id))));
  for (const q of Array.isArray(data.quotes) ? data.quotes : []) {
    if (!q || !ids.includes(q.id) || typeof q.priceUsd !== 'number'
        || !Number.isFinite(q.priceUsd) || q.priceUsd <= 0
        || !['live', 'delayed', 'partial'].includes(q.status)
        || !['coingecko', 'coinbase'].includes(q.source ?? '')
        || q.source !== data.provider) continue;
    next[q.id] = { quote: { ...q, decisionUsable: false }, retained: false };
  }
  return next;
}

export function cryptoDisplayForAsset(
  a: Pick<AssetItem, 'symbol' | 'memo'>, quotes: CryptoDisplayQuotes = {},
): CryptoDisplayQuote | undefined {
  const candidates = [coingeckoIdOf(a), SYMBOL_TO_COINGECKO[a.symbol.toUpperCase()] ?? ''];
  return candidates.filter(Boolean).map((id) => quotes[id]).find(Boolean);
}

export function cryptoPriceDisplay(row?: CryptoDisplayQuote, nowMs = Date.now()) {
  if (!row) return null;
  const q = row.quote;
  const current = !row.retained && cryptoQuoteDecisionUsable(q, nowMs);
  const sourceEpoch = exactAuthorityEpoch(q.sourceTimestamp);
  const sourceTime = sourceEpoch != null && sourceEpoch <= nowMs ? q.sourceTimestamp : null;
  const receivedEpoch = exactAuthorityEpoch(q.receivedAt);
  const receivedAt = receivedEpoch != null && receivedEpoch <= nowMs ? q.receivedAt : null;
  const provider = q.source === 'coinbase' ? 'Coinbase' : 'CoinGecko';
  const formatTime = (stamp: string) => new Date(stamp).toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
  const label = current ? 'リアルタイム' : row.retained || sourceTime ? '保存価格' : '時刻未確認';
  const detail = sourceTime ? `価格 ${formatTime(sourceTime)}`
    : receivedAt ? `価格時刻不明 · 受信 ${formatTime(receivedAt)}` : '価格時刻・受信時刻不明';
  return {
    priceUsd: q.priceUsd,
    changePct: typeof q.changePct === 'number' && Number.isFinite(q.changePct) ? q.changePct : null,
    label, detail: `${provider} · ${detail}`,
    delay: current ? 'LIVE' : 'UNKNOWN',
    // The exact original stamps remain readable without renewing source age.
    title: `${provider} · 価格時刻 ${sourceTime ?? '不明'} · 受信時刻 ${receivedAt ?? '不明'}`,
  };
}
