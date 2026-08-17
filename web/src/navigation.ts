export type RouteKey =
  | 'command'
  | 'watchlist'
  | 'notifications'
  | 'settings';

export type PrimaryRouteKey = RouteKey;
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

// Lean v13: one small, owner-facing navigation model. Asset Detail and
// Settings subsections remain contextual hashes, not extra workspace doors.
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

const ROUTE_HASHES: Record<RouteKey, string> = {
  command: '#today',
  watchlist: '#holdings',
  notifications: '#notifications',
  settings: '#settings',
};

// Only canonical surface hashes are routable. Retired engine/deep-link aliases
// deliberately do not redirect.
export const HASH_ROUTES: Readonly<Record<string, RouteKey>> = {
  '#today': 'command',
  '#holdings': 'watchlist',
  '#notifications': 'notifications',
  '#settings': 'settings',
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
