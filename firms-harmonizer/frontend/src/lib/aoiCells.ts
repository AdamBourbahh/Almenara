import { cellsToMultiPolygon, polygonToCells } from "h3-js";

export type CellPolygon = { type: "Polygon"; coordinates: number[][][] };

/**
 * R7 cells whose centres fall inside a GeoJSON polygon (holes included).
 * The polygon coordinates use [lng, lat] order.
 */
export function cellsFromPolygon(polygon: { coordinates: number[][][] }): string[] {
  return polygonToCells(polygon.coordinates, 7, true);
}

/**
 * Largest connected island of a cell set, expressed as a GeoJSON polygon whose
 * edges are the hexagon boundaries themselves, so the AOI perimeter follows the
 * cells. Returns `null` for an empty set.
 *
 * Removing interior cells can split the selection into several islands; only the
 * largest one is kept so the frozen single-polygon AOI contract still holds.
 */
export function polygonFromCells(cells: readonly string[]): CellPolygon | null {
  if (cells.length === 0) return null;
  const multi = cellsToMultiPolygon([...cells], true) as number[][][][];
  if (!Array.isArray(multi) || multi.length === 0) return null;
  let best = multi[0];
  let bestArea = -Infinity;
  for (const polygon of multi) {
    const ring = polygon[0] ?? [];
    let area = 0;
    for (let i = 0; i < ring.length - 1; i += 1) {
      area += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
    }
    const magnitude = Math.abs(area);
    if (magnitude > bestArea) {
      bestArea = magnitude;
      best = polygon;
    }
  }
  return { type: "Polygon", coordinates: best };
}
