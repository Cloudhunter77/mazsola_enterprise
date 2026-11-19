/** Hungarian formatting helpers. */

const HUF = new Intl.NumberFormat("hu-HU", {
  style: "currency",
  currency: "HUF",
  maximumFractionDigits: 0,
});

const HUF_COMPACT = new Intl.NumberFormat("hu-HU", {
  notation: "compact",
  maximumFractionDigits: 1,
});

const DATE = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "2-digit", day: "2-digit" });
const DATETIME = new Intl.DateTimeFormat("hu-HU", {
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});
const MONTH = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "short" });
const MONTH_LONG = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "long" });
const DAY = new Intl.DateTimeFormat("hu-HU", { month: "short", day: "numeric" });
const DAY_YEAR = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "short", day: "numeric" });
const DAY_TIME = new Intl.DateTimeFormat("hu-HU", {
  year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
});

export const ft = (value: number | string | null | undefined): string =>
  value == null ? "–" : HUF.format(Number(value));

/** Axis ticks: "12,3 E" rather than "12 345 Ft", so labels do not collide. */
export const ftCompact = (value: number): string => HUF_COMPACT.format(value);

export const date = (iso: string | null | undefined): string =>
  iso ? DATE.format(new Date(iso)) : "–";

export const dateTime = (iso: string | null | undefined): string =>
  iso ? DATETIME.format(new Date(iso)) : "–";

export const month = (iso: string): string => MONTH.format(new Date(iso));

/** "2026. november": a month as a heading in a list. */
export const monthLong = (at: Date): string => MONTH_LONG.format(at);

/** A plain date ("2026-12-10") is a day, not an instant: read it as local midnight, so it
 *  is the same day in every time zone. Anything with a time is an instant and parsed as one. */
const parse = (iso: string): Date => {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  return day ? new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3])) : new Date(iso);
};

/** "nov. 18." - a date in a list or a narrow column, where "2026. 11. 18." wrapped onto
 *  three lines. The year only when it is not this year. */
export const shortDate = (iso: string | null | undefined): string => {
  if (!iso) return "–";
  const at = parse(iso);
  return (at.getFullYear() === new Date().getFullYear() ? DAY : DAY_YEAR).format(at);
};

/** "2026. nov. 17. 17:30": when something happened, readable at a glance. */
export const dayTime = (iso: string | null | undefined): string =>
  iso ? DAY_TIME.format(new Date(iso)) : "–";

/** ISO timestamp -> the value a <input type="datetime-local"> expects, in local time.
 *  Slicing the ISO string directly would show UTC and silently shift the time. */
export const toLocalInput = (iso: string | null | undefined): string => {
  if (!iso) return "";
  const at = new Date(iso);
  const local = new Date(at.getTime() - at.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
};

/** The inverse: a datetime-local value is local time, and the API stores UTC. */
export const fromLocalInput = (value: string): string | null =>
  value ? new Date(value).toISOString() : null;

export const pct = (value: number | null | undefined, digits = 1): string =>
  value == null ? "–" : `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;

export const qty = (value: number | string | null | undefined, unit?: string | null): string => {
  if (value == null) return "–";
  const n = Number(value);
  const text = Number.isInteger(n) ? String(n) : n.toLocaleString("hu-HU");
  return unit ? `${text} ${unit}` : text;
};

/** Review reasons come from the API as machine keys; these are what a person reads. */
export const REVIEW_REASONS: Record<string, string> = {
  items_total_mismatch: "A tételek összege nem egyezik a végösszeggel",
  total_transcription_mismatch:
    "A végösszeg számként és leírt formában nem egyezik – valószínűleg lemaradt egy ezres jegy",
  line_transcription_mismatch:
    "Egy sor összege nem egyezik a blokkon látható számmal",
  vat_summary_mismatch: "Az ÁFA-blokk nem egyezik a végösszeggel",
  vat_row_mismatch: "Egy ÁFA-sor nettó + ÁFA értéke nem adja ki a bruttót",
  missing_total: "Hiányzik a végösszeg",
  non_positive_total: "A végösszeg nulla vagy negatív",
  implausible_total: "Irreálisan magas végösszeg",
  no_items: "Nincs felismert tétel",
  missing_merchant: "Hiányzik a bolt neve",
  missing_or_unparsable_date: "Hiányzó vagy értelmezhetetlen dátum",
  future_date: "A dátum a jövőben van",
  implausibly_old_date: "Irreálisan régi dátum",
  rounding_out_of_range: "A kerekítés 2 Ft-nál nagyobb",
  cash_total_not_multiple_of_five: "Készpénzes végösszeg, ami nem osztható 5-tel",
  missing_vat_rate: "Hiányzó ÁFA-kulcs",
  low_confidence: "A felismerés bizonytalan",
  low_confidence_line: "Legalább egy sor bizonytalan",
};

export const STATUS_LABELS: Record<string, string> = {
  pending: "Sorban áll",
  processing: "Feldolgozás alatt",
  parsed: "Feldolgozva",
  needs_review: "Ellenőrzendő",
  failed: "Sikertelen",
  confirmed: "Megerősítve",
};

/** "unknown" has no label on purpose: saying nothing beats saying "ismeretlen". */
export const PAYMENT_LABELS: Record<string, string> = {
  card: "Bankkártya",
  cash: "Készpénz",
  other: "Egyéb fizetés",
};

export const KIND_LABELS: Record<string, string> = {
  item: "Termék",
  deposit: "Betétdíj",
  discount: "Kedvezmény",
  rounding: "Kerekítés",
  fee: "Díj",
};
