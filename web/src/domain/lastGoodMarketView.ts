// 2026-11-15: a market view whose projection failed on the server (projection
// null, sourceStatus.error set) must not replace the device's last good copy.
// The live screen still shows the failure truthfully; only the saved copy that
// a reopened app paints first keeps the last view that actually computed.
type ViewLike = { projection?: unknown } | null | undefined;

export function marketViewToKeep<V extends ViewLike>(next: V, saved: V): V {
  const nextComputed = !!next && next.projection !== null && next.projection !== undefined;
  const savedComputed = !!saved && saved.projection !== null && saved.projection !== undefined;
  return !nextComputed && savedComputed ? saved : next;
}
