import { cellsToMultiPolygon, gridDisk, polygonToCells } from "h3-js";

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

/**
 * True when removing `cell` leaves the rest of the set connected.
 * Adding a cell never disconnects, so it always returns true in that case.
 * Interior holes are allowed; only removals that would split the area into
 * detached islands are rejected.
 */
export function removalKeepsConnected(cells: readonly string[], cell: string): boolean {
  const remaining = cells.filter((item) => item !== cell);
  if (remaining.length <= 1) return true;
  const members = new Set(remaining);
  const start = remaining[0];
  const seen = new Set([start]);
  const stack = [start];
  while (stack.length > 0) {
    const current = stack.pop() as string;
    for (const neighbour of gridDisk(current, 1)) {
      if (neighbour !== current && members.has(neighbour) && !seen.has(neighbour)) {
        seen.add(neighbour);
        stack.push(neighbour);
      }
    }
  }
  return seen.size === remaining.length;
}
