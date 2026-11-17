/** Where every screen lives.
 *
 *  Grouped by what you are doing, not by what got built when. The tab bar used to be a
 *  record of the build order: Blokkok and Tábla were two tabs showing the same receipts,
 *  while the shopping list and shelf labels - the two things used standing in a shop - hid
 *  behind buttons on the camera screen, and the system page was reachable only from a gear
 *  inside the table.
 *
 *  Five sections, because a phone's bottom bar holds five comfortably. Everything that is a
 *  variation of one of them - another way to record, another view of the same receipts -
 *  is a sub-page of that section rather than a sixth tab. Money - the plan, the month, what
 *  comes and goes every month, and the spending statistics - is one of them; the pages you
 *  open rarely (who can log in, what to fix, what the API costs, which version runs) sit
 *  behind the ⚙ instead of a tab. The URLs are the ones that already existed, so nothing
 *  bookmarked or saved to the home screen breaks.
 */

export interface Page { to: string; label: string }
export interface Section {
  glyph: string;
  label: string;
  pages: Page[];
  /** Other paths that belong here without being in the sub-navigation (detail screens). */
  also?: RegExp;
}

export const SECTIONS: Section[] = [
  {
    glyph: "📷",
    label: "Rögzítés",
    pages: [
      { to: "/", label: "Blokk" },
      { to: "/arcimkek", label: "Árcímke" },
      { to: "/kezi", label: "Kézzel" },
    ],
  },
  {
    glyph: "🛒",
    label: "Lista",
    pages: [{ to: "/lista", label: "Bevásárlás" }],
  },
  {
    glyph: "🧾",
    label: "Blokkok",
    pages: [
      { to: "/blokkok", label: "Lista" },
      { to: "/tabla", label: "Tábla" },
      { to: "/elszamolas", label: "Elszámolás" },
      { to: "/kategorizalas", label: "Kategorizálás" },
    ],
    also: /^\/blokkok\//,
  },
  {
    glyph: "🏷️",
    label: "Árak",
    pages: [
      { to: "/arak", label: "Ártörténet" },
      { to: "/polcarak", label: "Polcárak" },
    ],
  },
  {
    glyph: "💰",
    label: "Pénz",
    pages: [
      { to: "/penz", label: "Hónap" },
      { to: "/terv", label: "Terv" },
      { to: "/rendszeres", label: "Rendszeres" },
      { to: "/statisztika", label: "Statisztika" },
    ],
    also: /^\/megbeszeles$/,
  },
];

/** Behind the ⚙ in the top bar: looked at rarely, so not a tab. */
export const SETTINGS: Section = {
  glyph: "⚙",
  label: "Beállítások",
  pages: [
    { to: "/felhasznalok", label: "Felhasználók" },
    { to: "/javitani", label: "Javítani való" },
    { to: "/koltseg", label: "API költség" },
    { to: "/rendszer", label: "Rendszer" },
  ],
};

/** The section a path belongs to, or null for a path no section claims. */
export function sectionFor(pathname: string): Section | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  return (
    [...SECTIONS, SETTINGS].find(
      (section) =>
        section.pages.some((page) => page.to === path) || section.also?.test(path),
    ) ?? null
  );
}
