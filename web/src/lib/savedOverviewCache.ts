/** Protected explanations stay only in bounded memory, with a login/context/subject key. */
export function createSavedReadCache<T>(capacity = 64) {
  const entries = new Map<string, { value: T; until: number }>();
  return {
    get(key: string, now = Date.now()): T | undefined {
      const row = entries.get(key);
      if (!row || now >= row.until) { entries.delete(key); return undefined; }
      return row.value;
    },
    put(key: string, value: T, ttl: number, now = Date.now()) {
      entries.delete(key); entries.set(key, { value, until: now + ttl });
      while (entries.size > capacity) entries.delete(entries.keys().next().value!);
    },
    clear() { entries.clear(); },
  };
}
