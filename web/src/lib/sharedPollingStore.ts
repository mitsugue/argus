export type SnapshotUpdate<T> = T | ((current: T) => T);
export type SnapshotSetter<T> = (update: SnapshotUpdate<T>) => void;

export interface SharedPollingStore<T> {
  getSnapshot: () => T;
  setSnapshot: SnapshotSetter<T>;
  subscribe: (listener: () => void) => () => void;
}

/**
 * One acquisition lifecycle shared by every React consumer of the same query.
 * The first subscriber starts polling; the last subscriber stops it. Query
 * modules may keep one store globally or one store per canonical parameter key.
 */
export function createSharedPollingStore<T>(
  initialSnapshot: T,
  start: (setSnapshot: SnapshotSetter<T>, getSnapshot: () => T) => () => void,
): SharedPollingStore<T> {
  let snapshot = initialSnapshot;
  let stop: (() => void) | null = null;
  const listeners = new Set<() => void>();

  const getSnapshot = () => snapshot;
  const setSnapshot: SnapshotSetter<T> = (update) => {
    const next = typeof update === 'function'
      ? (update as (current: T) => T)(snapshot)
      : update;
    if (Object.is(next, snapshot)) return;
    snapshot = next;
    for (const listener of [...listeners]) listener();
  };
  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    if (listeners.size === 1) stop = start(setSnapshot, getSnapshot);
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0 && stop) {
        const stopCurrent = stop;
        stop = null;
        stopCurrent();
      }
    };
  };

  return { getSnapshot, setSnapshot, subscribe };
}
