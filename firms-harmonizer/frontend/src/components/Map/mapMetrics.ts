import { cellArea, UNITS } from "h3-js";
import type { H3MapSummaryHex } from "../../api/types";

/** Integrate only the cells drawn on the map, using their exact physical areas. */
export function summarizeMappedYear(cells: H3MapSummaryHex[], hideIndustrial: boolean) {
  const hexagons = hideIndustrial ? cells.filter((cell) => !cell.is_industrial_site) : cells;
  let energyGJ = 0;
  let footprintKm2 = 0;
  let detections = 0;
  for (const cell of hexagons) {
    const area = cellArea(cell.h3_index, UNITS.km2);
    energyGJ += cell.mean_annual_fre * area / 1000;
    footprintKm2 += area;
    detections += cell.raw_pixel_count;
  }
  return { hexagons, energyGJ, footprintKm2, detections };
}

/** Logarithmic, shared cross-year scale; reference is an all-years upper bound.
 *  Any non-zero value keeps a visible floor so small fires never vanish next to a mega-fire. */
export function colorIntensity(value: number, reference: number): number {
  if (!(value > 0)) return 0;
  const t = Math.log1p(value) / Math.log1p(Math.max(1, reference));
  return Math.min(1, Math.max(0.22, t));
}

/** Robust colour reference for the displayed period: 95th percentile of positive
 *  values, falling back to the maximum for small samples. This keeps a quiet day,
 *  month or year legible instead of rendering it as a faint wash against the
 *  largest fire of the whole record. */
export function robustReference(values: readonly number[]): number {
  const positives = values.filter((value) => Number.isFinite(value) && value > 0).sort((a, b) => a - b);
  if (positives.length === 0) return 1;
  if (positives.length < 8) return Math.max(positives[positives.length - 1], 1);
  const index = Math.min(positives.length - 1, Math.floor(positives.length * 0.95));
  return Math.max(positives[index], 1);
}
