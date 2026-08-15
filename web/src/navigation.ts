export type RouteKey =
  | 'command'
  | 'watchlist'
  | 'notifications'
  | 'settings'
  | 'regime';

export type PrimaryRouteKey = Exclude<RouteKey, 'regime'>;
export type SettingsSection = 'status' | 'recovery' | 'help';

export interface NavigationDefinition {
  route: PrimaryRouteKey;
  desktopLabel: string;
  mobileLabel: string;
  hash: string;
  swipeOrder: number;
}

export interface ParsedLocation {
  route: RouteKey;
  asset?: { symbol: string; section?: string };
  portfolioOpen?: boolean;
  settingsSection?: SettingsSection;
}

// Lean v13: one small, owner-facing navigation model. Market replay remains a
// contextual destination, not a fifth workspace door.
export const NAVIGATION: readonly NavigationDefinition[] = [
  { route: 'command', desktopLabel: 'Today', mobileLabel: 'Today',
    hash: '#today', swipeOrder: 0 },
  { route: 'watchlist', desktopLabel: 'Holdings / Watchlist', mobileLabel: 'Holdings',
    hash: '#holdings', swipeOrder: 1 },
  { route: 'notifications', desktopLabel: 'Notifications', mobileLabel: 'Alerts',
    hash: '#notifications', swipeOrder: 2 },
  { route: 'settings', desktopLabel: 'Settings', mobileLabel: 'Settings',
    hash: '#settings', swipeOrder: 3 },
] as const;

export const PRIMARY_NAVIGATION = [...NAVIGATION]
  .sort((left, right) => left.swipeOrder - right.swipeOrder);

// Explicit route hashes keep contextual routes addressable without putting
// them in NAVIGATION.
const ROUTE_HASHES: Record<RouteKey, string> = {
  command: '#today',
  watchlist: '#holdings',
  notifications: '#notifications',
  settings: '#settings',
  regime: '#market',
};

// Legacy hashes remain read-compatible. They resolve into the smaller surface
// rather than keeping duplicate pages alive.
export const HASH_ROUTES: Readonly<Record<string, RouteKey>> = {
  '#today': 'command',
  '#holdings': 'watchlist',
  '#assets': 'watchlist',
  '#positions': 'watchlist',
  '#notifications': 'notifications',
  '#settings': 'settings',
  '#quality': 'settings',
  '#backup': 'settings',
  '#guide': 'settings',
  '#market': 'regime',
};

const safeDecode = (value: string) => {
  try { return decodeURIComponent(value); } catch { return value; }
};

export function parseLocationHash(hash: string): ParsedLocation | undefined {
  if (hash.startsWith('#asset/')) {
    const [rawSymbol = '', rawSection] = hash.slice('#asset/'.length).split('/', 2);
    const symbol = safeDecode(rawSymbol).trim().toUpperCase();
    if (!symbol) return undefined;
    const section = rawSection ? safeDecode(rawSection).trim() : undefined;
    return { route: 'watchlist', asset: { symbol, section: section || undefined } };
  }
  if (hash.startsWith('#settings/')) {
    const value = hash.slice('#settings/'.length);
    const settingsSection: SettingsSection = value === 'recovery' || value === 'help'
      ? value : 'status';
    return { route: 'settings', settingsSection };
  }
  if (hash.startsWith('#guide:')) return { route: 'settings', settingsSection: 'help' };
  if (hash === '#review') return { route: 'settings', settingsSection: 'help' };
  if (hash === '#positions') return { route: 'watchlist', portfolioOpen: true };
  if (hash === '#backup') return { route: 'settings', settingsSection: 'recovery' };
  if (hash === '#quality') return { route: 'settings', settingsSection: 'status' };
  if (hash === '#guide') return { route: 'settings', settingsSection: 'help' };
  const route = HASH_ROUTES[hash];
  return route ? { route } : undefined;
}

export function assetDetailHash(symbol: string, section?: string) {
  const base = `#asset/${encodeURIComponent(symbol.trim().toUpperCase())}`;
  return section ? `${base}/${encodeURIComponent(section)}` : base;
}

export function routeHash(route: RouteKey) {
  return ROUTE_HASHES[route];
}

export function routeLabel(route: RouteKey) {
  if (route === 'regime') return 'Market Context';
  return NAVIGATION.find((item) => item.route === route)?.desktopLabel ?? route;
}

export function primaryRouteIndex(route: RouteKey) {
  return PRIMARY_NAVIGATION.findIndex((item) => item.route === route);
}

export function pageDirection(from: RouteKey, to: RouteKey): 1 | -1 {
  const fromIndex = primaryRouteIndex(from);
  const toIndex = primaryRouteIndex(to);
  if (fromIndex < 0 || toIndex < 0 || fromIndex === toIndex) return 1;
  return toIndex > fromIndex ? 1 : -1;
}
