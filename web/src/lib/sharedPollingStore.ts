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
  start: (setSnapshot: SnapshotSetter<T>, getSnapshot: () => T, restored: boolean) => () => void,
  resumeKey?: string,
  canCheckpoint?: (value: T) => boolean,
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
    // Incomplete initial loads are not a saved view. Keep its original data
    // and reception timestamps; hydration never invents a new reception.
    if (resumeKey && (!canCheckpoint || canCheckpoint(next))
      && !(next && typeof next === 'object' && 'loading' in next && next.loading === true)
      && sessionViewCheckpoint.keep(resumeKey, next)) void sessionViewCheckpoint.flush();
    for (const listener of [...listeners]) listener();
  };
  const subscribe = (listener: () => void) => {
    listeners.add(listener);
    if (listeners.size === 1) stop = start(setSnapshot, getSnapshot,
      !!resumeKey && sessionViewCheckpoint.hasRestored(resumeKey));
    return () => {
      listeners.delete(listener);
      if (listeners.size === 0 && stop) {
        const stopCurrent = stop;
        stop = null;
        stopCurrent();
      }
    };
  };

  if (resumeKey) sessionViewCheckpoint.bind(resumeKey, value => {
    snapshot = value as T;
    for (const listener of [...listeners]) listener();
  });
  return { getSnapshot, setSnapshot, subscribe };
}
import { sessionViewCheckpoint } from './sessionViewCheckpoint';
