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

export const ft = (value: number | string | null | undefined): string =>
  value == null ? "–" : HUF.format(Number(value));

/** Axis ticks: "12,3 E" rather than "12 345 Ft", so labels do not collide. */
export const ftCompact = (value: number): string => HUF_COMPACT.format(value);

export const date = (iso: string | null | undefined): string =>
  iso ? DATE.format(new Date(iso)) : "–";

export const dateTime = (iso: string | null | undefined): string =>
  iso ? DATETIME.format(new Date(iso)) : "–";

export const month = (iso: string): string => MONTH.format(new Date(iso));

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

export const KIND_LABELS: Record<string, string> = {
  item: "Termék",
  deposit: "Betétdíj",
  discount: "Kedvezmény",
  rounding: "Kerekítés",
  fee: "Díj",
};
