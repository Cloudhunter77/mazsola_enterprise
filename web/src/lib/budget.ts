/** Small helpers the Pénz screens share: names for owners, tags and months. */

import type { LineKind, Period, Person } from "./api";

export const KIND_LABELS: Record<LineKind, string> = {
  fix: "Fix",
  valtozo: "Változó",
  celalap: "Célalap",
  megtakaritas: "Megtakarítás",
};

export const KINDS: LineKind[] = ["valtozo", "fix", "celalap", "megtakaritas"];

/** Set aside rather than spent: no receipt ever shows these, so they have no "actual". */
export const isAside = (kind: LineKind) => kind === "celalap" || kind === "megtakaritas";

const MONTH_LONG = new Intl.DateTimeFormat("hu-HU", { month: "long" });
const MONTH_SHORT = new Intl.DateTimeFormat("hu-HU", { month: "short" });
const DAY = new Intl.DateTimeFormat("hu-HU", { month: "short", day: "numeric" });

/** A date-only ISO string read as a local date - `new Date("2026-11-01")` would be UTC
 *  midnight, which is still 31 October in some time zones. */
export const localDate = (iso: string): Date => {
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
};

const capital = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** "November", or "2027. január" once it is not this year. */
export function monthLabel(iso: string, thisYear = new Date().getFullYear()): string {
  const day = localDate(iso);
  const name = capital(MONTH_LONG.format(day));
  return day.getFullYear() === thisYear ? name : `${day.getFullYear()}. ${MONTH_LONG.format(day)}`;
}

/** Column headings in the plan grid: "nov.", "2027 jan." */
export function monthShort(iso: string, thisYear = new Date().getFullYear()): string {
  const day = localDate(iso);
  const name = MONTH_SHORT.format(day);
  return day.getFullYear() === thisYear ? name : `${day.getFullYear()} ${name}`;
}

export const dayLabel = (iso: string) => DAY.format(localDate(iso));

/** "nov. 2. óta", or "okt. 3. – nov. 1." for a period that has ended. */
export function periodRange(period: Period): string {
  if (!period.ends_on) return `${dayLabel(period.starts_on)} óta`;
  const last = localDate(period.ends_on);
  last.setDate(last.getDate() - 1);
  return `${dayLabel(period.starts_on)} – ${DAY.format(last)}`;
}

/** Közös first, then the people in the order they joined. */
export function owners(users: Person[]): { id: string | null; name: string }[] {
  return [{ id: null, name: "Közös" }, ...users.map((u) => ({ id: u.id, name: u.display_name }))];
}

export function ownerName(users: Person[], id: string | null): string {
  if (id === null) return "Közös";
  return users.find((u) => u.id === id)?.display_name ?? "?";
}

/** Today as `YYYY-MM-DD` in the browser's own time zone. */
export function todayIso(): string {
  const now = new Date();
  now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
  return now.toISOString().slice(0, 10);
}

/** Accepts `1 234`, `1234`, `1234,56` - whatever gets typed on a Hungarian keyboard. */
export function amountOf(raw: string): number | null {
  const cleaned = raw.replace(/\s| /g, "").replace(",", ".");
  if (!cleaned) return null;
  const value = Number(cleaned);
  return Number.isFinite(value) ? value : null;
}

/** An amount for an input field: whole forints, no separators to fight with. */
export const plain = (value: string | number | null | undefined): string =>
  value == null ? "" : String(Math.round(Number(value)));

/** The five priorities the spreadsheet's wishlist used, 1 (lowest) to 5. */
export const PRIORITIES: Record<number, string> = {
  1: "Alacsony", 2: "Alacsony-közepes", 3: "Közepes", 4: "Közép-magas", 5: "Magas",
};

/** "Savings (Balázs)": a pocket by name and whose account it is in. */
export function pocketLabel(pocket: { name: string; holder_id: string | null }, users: Person[]): string {
  const holder = users.find((u) => u.id === pocket.holder_id)?.display_name;
  return holder ? `${pocket.name} (${holder})` : pocket.name;
}
