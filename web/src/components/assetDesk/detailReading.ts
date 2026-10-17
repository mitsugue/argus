/** 表示だけの整理。意味の違う文章は統合せず、同じ文章の再掲だけを省く。 */
export function uniqueDetailText(values: Array<string | null | undefined>, already: string[] = []): string[] {
  const key = (text: string) => text.trim().replace(/\s+/g, '').replace(/[。．.]+$/u, '');
  const seen = new Set(already.filter(Boolean).map(key));
  return values.filter((text): text is string => {
    if (!text?.trim() || seen.has(key(text))) return false;
    seen.add(key(text));
    return true;
  });
}
export function detailTime(iso: string): string {
  if (/^\d{4}[-/]\d{2}[-/]\d{2}$/.test(iso)) return iso.replaceAll('-', '/');
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString('ja-JP', {
    timeZone: 'Asia/Tokyo', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}
