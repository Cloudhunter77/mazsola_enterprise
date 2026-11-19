/** Lists by month: the receipts, the shared bills.
 *
 *  A long list of dated rows reads better under a heading per month - the heading carries
 *  the year and month, so each row only needs "nov. 17.", and you can see at a glance where
 *  one month ends.
 */

import { monthLong } from "./format";

export interface MonthGroup<T> { key: string; label: string; items: T[] }

/** Newest month first. Rows without a date come first, under `undated`: they are the newest
 *  (still being read) or the ones that need looking at. */
export function groupByMonth<T>(
  items: T[],
  when: (item: T) => string | null,
  undated = "Dátum nélkül",
): MonthGroup<T>[] {
  const none: MonthGroup<T> = { key: "undated", label: undated, items: [] };
  const months = new Map<string, MonthGroup<T> & { at: number }>();
  for (const item of items) {
    const iso = when(item);
    if (!iso) {
      none.items.push(item);
      continue;
    }
    const at = new Date(iso);
    const key = `${at.getFullYear()}-${String(at.getMonth() + 1).padStart(2, "0")}`;
    let group = months.get(key);
    if (!group) {
      group = { key, label: monthLong(at), items: [], at: new Date(at.getFullYear(), at.getMonth()).getTime() };
      months.set(key, group);
    }
    group.items.push(item);
  }
  const sorted = [...months.values()].sort((a, b) => b.at - a.at);
  return none.items.length ? [none, ...sorted] : sorted;
}
