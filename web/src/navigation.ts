export type RouteKey =
  | 'command'
  | 'regime'
  | 'watchlist'
  | 'core'
  | 'backup'
  | 'quality'
  | 'guide';

export type NavigationGroup = 'primary' | 'system';

export interface NavigationDefinition {
  route: RouteKey;
  desktopLabel: string;
  mobileLabel: string;
  hash: string;
  group: NavigationGroup;
  mobilePrimary: boolean;
  swipeOrder: number | null;
}

// One route model drives every navigation surface. AI Review is deliberately
// absent: it is a hidden support sheet (#review), not Positions & Risk.
export const NAVIGATION: readonly NavigationDefinition[] = [
  { route: 'command', desktopLabel: 'Today', mobileLabel: 'Today',
    hash: '#today', group: 'primary', mobilePrimary: true, swipeOrder: 0 },
  { route: 'watchlist', desktopLabel: 'Asset Desk', mobileLabel: 'Assets',
    hash: '#assets', group: 'primary', mobilePrimary: true, swipeOrder: 1 },
  { route: 'core', desktopLabel: 'Positions & Risk', mobileLabel: 'Review',
    hash: '#positions', group: 'primary', mobilePrimary: true, swipeOrder: 2 },
  { route: 'regime', desktopLabel: 'Market Context', mobileLabel: 'Market',
    hash: '#market', group: 'primary', mobilePrimary: true, swipeOrder: 3 },
  { route: 'quality', desktopLabel: 'Data Quality', mobileLabel: 'Data Quality',
    hash: '#quality', group: 'system', mobilePrimary: false, swipeOrder: null },
  { route: 'backup', desktopLabel: 'Backup', mobileLabel: 'Backup',
    hash: '#backup', group: 'system', mobilePrimary: false, swipeOrder: null },
  { route: 'guide', desktopLabel: 'Guide', mobileLabel: 'Guide',
    hash: '#guide', group: 'system', mobilePrimary: false, swipeOrder: null },
] as const;

export const PRIMARY_NAVIGATION = NAVIGATION
  .filter((item) => item.group === 'primary')
  .sort((left, right) => (left.swipeOrder ?? 99) - (right.swipeOrder ?? 99));

export const SYSTEM_NAVIGATION = NAVIGATION
  .filter((item) => item.group === 'system');

export const HASH_ROUTES = Object.fromEntries(
  NAVIGATION.map((item) => [item.hash, item.route]),
) as Record<string, RouteKey>;

export function navigationFor(route: RouteKey) {
  return NAVIGATION.find((item) => item.route === route)!;
}

export function routeHash(route: RouteKey) {
  return navigationFor(route).hash;
}

export function routeLabel(route: RouteKey) {
  return navigationFor(route).desktopLabel;
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
