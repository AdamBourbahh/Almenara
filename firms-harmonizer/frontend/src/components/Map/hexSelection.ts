import { cellArea, cellsToMultiPolygon, getResolution, isValidCell, latLngToCell, polygonToCells } from "h3-js";
import type { GeoJSONPolygon } from "../../api/types";

export const MAX_SELECTED_HEXAGONS = 256;
export const MAX_GRID_HEXAGONS = 6000;

/** Fill only enclosed holes of the actual cell union, never its convex hull. */
export function fillHexagonPerimeter(cells: readonly string[]): string[] {
  const unique = [...new Set(cells)];
  if (!unique.length) throw new Error("Close a perimeter to enable Fill.");
  if (unique.length > MAX_SELECTED_HEXAGONS) throw new Error(`Select at most ${MAX_SELECTED_HEXAGONS} hexagons.`);
  if (unique.some(cell => !isValidCell(cell) || getResolution(cell) !== 7)) {
    throw new Error("Select valid H3 resolution 7 cells.");
  }
  const polygons = cellsToMultiPolygon(unique, true);
  if (polygons.length !== 1) throw new Error("Join the separate groups before using Fill.");
  if (polygons[0].length < 2) throw new Error("No enclosed cells to fill. Close a perimeter around unselected cells to enable Fill.");
  const filled = polygonToCells([polygons[0][0]], 7, true).sort();
  if (filled.length > MAX_SELECTED_HEXAGONS) {
    throw new Error(`Fill would exceed the ${MAX_SELECTED_HEXAGONS}-cell limit. Use a smaller perimeter.`);
  }
  const filledSet = new Set(filled);
  if (unique.some(cell => !filledSet.has(cell))) throw new Error("This perimeter cannot be filled exactly. Adjust the selected cells.");
  polygonFromHexagons(filled);
  return filled;
}

/** Add/erase strokes are idempotent when the pointer revisits a cell. */
export function paintHexagons(cells: readonly string[], stroke: readonly string[], add: boolean): string[] {
  const selected = new Set(cells);
  for (const cell of stroke) {
    if (!add) selected.delete(cell);
    else if (selected.size < MAX_SELECTED_HEXAGONS) selected.add(cell);
  }
  return [...selected];
}

/** Sample the pointer segment, including intermediate cells on fast movements. */
export function hexagonsAlongPointerSegment(
  start: readonly [number, number], end: readonly [number, number],
  unproject: (point: [number, number]) => number[]
): string[] {
  const distance = Math.hypot(end[0] - start[0], end[1] - start[1]);
  if (!Number.isFinite(distance)) return [];
  const steps = Math.max(1, Math.ceil(distance / 2));
  const cells = new Set<string>();
  for (let i = 0; i <= steps; i++) {
    const [lng, lat] = unproject([start[0] + (end[0] - start[0]) * i / steps, start[1] + (end[1] - start[1]) * i / steps]);
    if (Number.isFinite(lat) && Number.isFinite(lng) && Math.abs(lat) <= 85 && Math.abs(lng) <= 180) {
      cells.add(latLngToCell(lat, lng, 7));
    }
  }
  return [...cells];
}

/** Preserve holes and require a lossless R7 round trip through the polygon API. */
export function polygonFromHexagons(cells: readonly string[]): GeoJSONPolygon {
  const unique = [...new Set(cells)].sort();
  if (!unique.length) throw new Error("Select at least one hexagon.");
  if (unique.length > MAX_SELECTED_HEXAGONS) throw new Error(`Select at most ${MAX_SELECTED_HEXAGONS} hexagons.`);
  if (unique.some(cell => !isValidCell(cell) || getResolution(cell) !== 7)) {
    throw new Error("Select valid H3 resolution 7 cells.");
  }
  const polygons = cellsToMultiPolygon(unique, true);
  if (polygons.length !== 1) throw new Error("Select one connected area. Join the separate groups with selected cells or remove a group.");
  const coordinates = polygons[0];
  if (coordinates.length > 16 || coordinates.reduce((sum, ring) => sum + ring.length, 0) > 512) {
    throw new Error("This boundary is too complex. Use fewer cells or a more compact selection.");
  }
  const recovered = polygonToCells(coordinates, 7, true).sort();
  if (recovered.length !== unique.length || recovered.some((cell, i) => cell !== unique[i])) {
    throw new Error("This selection cannot be represented exactly. Adjust the selected cells.");
  }
  return { type: "Polygon", coordinates };
}

export function selectedHexagonArea(cells: readonly string[]): number {
  return [...new Set(cells)].reduce((sum, cell) => sum + cellArea(cell, "km2"), 0);
}

/** Bound grid work before polyfilling; an overview never allocates a global R7 grid. */
export function hexagonsInView(west: number, south: number, east: number, north: number): string[] {
  if (![west, south, east, north].every(Number.isFinite) || west >= east || south >= north
    || west < -180 || east > 180 || south < -85 || north > 85) return [];
  const estimatedArea = (east - west) * (north - south) * 12364 * Math.cos((north + south) * Math.PI / 360);
  if (estimatedArea > MAX_GRID_HEXAGONS * 3) return [];
  const cells = polygonToCells([[[west, south], [east, south], [east, north], [west, north], [west, south]]], 7, true);
  return cells.length > MAX_GRID_HEXAGONS ? [] : cells;
}
