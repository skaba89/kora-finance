export const PAGE_SIZES = [25, 50, 100] as const;
export type TableDensity = "comfortable" | "compact";

/** Seules les colonnes facultatives déclarées peuvent être masquées. */
export function optionalColumns<T extends string>(query: Record<string, string | string[] | undefined>, allowed: readonly T[]): T[] {
  if (query.colonnes !== "1") return [...allowed];
  const selected = Array.isArray(query.colonne) ? query.colonne : [query.colonne];
  return allowed.filter(column => selected.includes(column));
}

export function tablePreferences(query: Record<string, string | string[] | undefined>, defaultSize: (typeof PAGE_SIZES)[number] = 50) {
  const one = (value: string | string[] | undefined) => Array.isArray(value) ? value[0] : value;
  const size = PAGE_SIZES.find(value => String(value) === one(query.taille)) ?? defaultSize;
  const rawPage = one(query.page) ?? "1";
  const candidate = /^\d+$/.test(rawPage) ? Number(rawPage) : 1;
  const page = candidate >= 1 && Number.isSafeInteger(candidate) && Number.isSafeInteger((candidate - 1) * size) ? candidate : 1;
  const density: TableDensity = one(query.densite) === "compact" ? "compact" : "comfortable";
  return { size, page, density, offset: (page - 1) * size };
}

/** Garde les bornes cohérentes même si une page a disparu après une mutation. */
export function tableRange(total: number, offset: number, count: number, size: number) {
  return { from: count ? offset + 1 : 0, to: count ? offset + count : 0, lastPage: Math.max(1, Math.ceil(total / size)) };
}
