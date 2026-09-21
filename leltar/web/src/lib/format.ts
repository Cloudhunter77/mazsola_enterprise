/** Hungarian formatting helpers, and the words behind the machine-readable flags. */

const HUF = new Intl.NumberFormat("hu-HU", {
  style: "currency",
  currency: "HUF",
  maximumFractionDigits: 0,
});

const DATE = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "2-digit", day: "2-digit" });
const DATETIME = new Intl.DateTimeFormat("hu-HU", {
  year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
});
const MONTH = new Intl.DateTimeFormat("hu-HU", { year: "numeric", month: "short" });

export const ft = (value: number | string | null | undefined): string =>
  value == null ? "–" : HUF.format(Number(value));

export const date = (iso: string | null | undefined): string =>
  iso ? DATE.format(new Date(iso)) : "–";

export const dateTime = (iso: string | null | undefined): string =>
  iso ? DATETIME.format(new Date(iso)) : "–";

export const month = (iso: string): string => MONTH.format(new Date(iso));

export const pct = (value: number | null | undefined, digits = 0): string =>
  value == null ? "–" : `${(value * 100).toFixed(digits)}%`;

/** The rules hand out machine keys; these are what a person reads. Each one says what the
 *  app did as well as what it noticed - a dropped brand is not the same as a warning. */
/** Counts, with the Hungarian plural that is not one: 3 tétel, not 3 tételek. */
export const count = (value: number, singular: string): string => `${value} ${singular}`;

export const REVIEW_REASONS: Record<string, string> = {
  generic_name: "A név semmitmondó – írd át valamire, amit később megtalálsz",
  unverifiable_brand: "A márkát nem lehetett elolvasni a képen, ezért töröltük",
  unverifiable_serial: "A sorozatszámot nem lehetett elolvasni a képen, ezért töröltük",
  unknown_category: "Ismeretlen kategória – Egyéb alá került",
  unusable_box: "A gép nem tudta bejelölni a tárgyat, ezért az egész kép lett a képe",
  implausible_quantity: "Irreális darabszám",
  low_confidence_object: "A gép bizonytalan ebben a tételben",
  low_confidence: "A gép bizonytalan az egész fényképben",
  no_objects: "A képen nem talált megnevezhető tárgyat",
  too_many_objects: "Több tárgy volt a képen, mint a korlát – a bizonytalanabbak kimaradtak",
};

export const PHOTO_STATUS: Record<string, string> = {
  pending: "Sorban áll",
  processing: "Feldolgozás alatt",
  identified: "Felismerve",
  needs_review: "Ellenőrzendő",
  failed: "Sikertelen",
  reviewed: "Átnézve",
};

export const ITEM_STATUS: Record<string, string> = {
  draft: "Javaslat",
  confirmed: "Megerősítve",
  rejected: "Elvetve",
};

export const CONDITIONS: Record<string, string> = {
  new: "Új",
  good: "Jó",
  used: "Használt",
  worn: "Kopott",
  broken: "Hibás",
  unknown: "Ismeretlen",
};

export const PLACE_KINDS: Record<string, string> = {
  building: "Épület",
  room: "Helyiség",
  storage: "Tároló",
};
