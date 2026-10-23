// Today の中の決まったブロックへなめらかに移る。タイルと画面下の帯で同じ動きにそろえる。
export function jumpTo(id: string, openRow?: string) {
  const target = document.getElementById(id);
  if (openRow) {
    const row = document.querySelector<HTMLDetailsElement>(`.today-strip__row[data-row="${openRow}"]`);
    if (row) { row.open = true; row.scrollIntoView({ behavior: 'smooth', block: 'center' }); return; }
  }
  target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
