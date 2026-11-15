const EARTH_RADIUS_KM = 6371.0088;
/** Mirrors the server's WGS84 preflight limit. */
export const MAX_AOI_AREA_KM2 = 1_250_000;

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

/** Spherical excess area of one closed ring in km² (independent of winding). */
function ringAreaKm2(ring: number[][]): number {
  if (ring.length < 4) return 0;
  let total = 0;
  for (let i = 0; i < ring.length - 1; i += 1) {
    const [lng1, lat1] = ring[i];
    const [lng2, lat2] = ring[i + 1];
    total += toRadians(lng2 - lng1) * (2 + Math.sin(toRadians(lat1)) + Math.sin(toRadians(lat2)));
  }
  return Math.abs((total * EARTH_RADIUS_KM * EARTH_RADIUS_KM) / 2);
}

/**
 * Geodesic area of a GeoJSON polygon in km²: exterior ring minus its holes.
 * Matches the server's WGS84 preflight closely enough to reject oversized AOIs
 * before the request leaves the browser.
 */
export function polygonAreaKm2(coordinates: number[][][]): number {
  const [outer, ...holes] = coordinates;
  if (!outer || outer.length < 4) return 0;
  const area = ringAreaKm2(outer) - holes.reduce((sum, ring) => sum + ringAreaKm2(ring), 0);
  return Math.max(0, area);
}
