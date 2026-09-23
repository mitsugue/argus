export type RouteKey =
  | 'command'
  | 'watchlist'
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
  { route: 'watchlist', desktopLabel: 'Watchlist', mobileLabel: 'Watchlist',
    hash: '#holdings', swipeOrder: 1 },
  { route: 'settings', desktopLabel: 'Settings', mobileLabel: 'Settings',
    hash: '#settings', swipeOrder: 2 },
] as const;

// 13M remains an independently deployed, read-only research application.
// Keep this as a plain navigation link: ARGUS must not fetch its data, start
// its jobs, or imply that an unverified candidate is a trading instruction.
export const THIRTEEN_M_NAVIGATION = {
  desktopLabel: '13M',
  mobileLabel: '13M',
  href: 'https://argus-13m-shadow.onrender.com/',
} as const;

export const PRIMARY_NAVIGATION = [...NAVIGATION]
  .sort((left, right) => left.swipeOrder - right.swipeOrder);

const ROUTE_HASHES: Record<RouteKey, string> = {
  command: '#today',
  watchlist: '#holdings',
  settings: '#settings',
};

// Only canonical surface hashes are routable. Retired Alerts landing links go
// to Today, where their news and SQ receipts are now presented.
export const HASH_ROUTES: Readonly<Record<string, RouteKey>> = {
  '#today': 'command',
  '#holdings': 'watchlist',
  '#notifications': 'command',
  '#settings': 'settings',
};

const safeDecode = (value: string) => {
  try { return decodeURIComponent(value); } catch { return value; }
};

export function parseLocationHash(hash: string): ParsedLocation | undefined {
  // Keep issued notification links stable while their detail has moved to
  // Today. The old Alerts landing page remains separately routable during the
  // migration, but a direct receipt must not strand the owner there.
  if (/^#(?:today|notifications)\/news\/[A-Za-z0-9:_-]{1,150}$/.test(hash)) return { route: 'command' };
  if (/^#(?:today|notifications)\/sq\/jp-monthly-sq-\d{4}-\d{2}$/.test(hash)) return { route: 'command' };
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
