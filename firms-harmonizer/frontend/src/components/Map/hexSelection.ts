import { cellArea, cellsToMultiPolygon, getResolution, isValidCell, polygonToCells } from "h3-js";
import type { GeoJSONPolygon } from "../../api/types";

export const MAX_SELECTED_HEXAGONS = 256;
export const MAX_GRID_HEXAGONS = 6000;

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
