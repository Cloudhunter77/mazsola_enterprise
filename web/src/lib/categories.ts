import type { Category } from "./api";

/** The category tree as a picker shows it: each main category with its subcategories. */
export function groupCategories(categories: Category[]) {
  const order = (a: Category, b: Category) =>
    a.sort_order - b.sort_order || a.name.localeCompare(b.name, "hu");
  return categories
    .filter((category) => category.parent_id === null)
    .sort(order)
    .map((parent) => ({
      parent,
      children: categories.filter((c) => c.parent_id === parent.id).sort(order),
    }));
}
