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

/** Logarithmic, shared cross-year scale; reference is an all-years upper bound. */
export function colorIntensity(value: number, reference: number): number {
  return Math.min(1, Math.log1p(Math.max(0, value)) / Math.log1p(Math.max(1, reference)));
}
