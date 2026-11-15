/** Geocoder results are filtered locally even when the provider ignores its bounds. */
export interface ApprovedRegion { label: string; bounds: [number, number, number, number] }
export interface LocationResult { label: string; longitude: number; latitude: number; region: ApprovedRegion }
export function approvedRegion(lon: number, lat: number, regions: ApprovedRegion[]) {
  return regions.find(({ bounds: [w,s,e,n] }) => lon >= w && lon <= e && lat >= s && lat <= n);
}
export function locationBounds(lon: number, lat: number, half: number, regions: ApprovedRegion[]): [number,number,number,number] | null {
  const region = approvedRegion(lon,lat,regions);
  if (!region) return null;
  const [w,s,e,n] = region.bounds;
  return [Math.max(w,lon-half),Math.max(s,lat-half),Math.min(e,lon+half),Math.min(n,lat+half)];
}
export async function searchLocations(query: string, regions: ApprovedRegion[], signal: AbortSignal): Promise<LocationResult[]> {
  const combined = AbortSignal.any([signal, AbortSignal.timeout(5000)]);
  const batches = await Promise.allSettled(regions.map(async region => {
    const params = new URLSearchParams({q:query.slice(0,120),bbox:region.bounds.join(','),limit:'5',lang:'en'});
    const response = await fetch(`https://photon.komoot.io/api/?${params}`,{signal:combined});
    if (!response.ok) throw new Error('Location search unavailable');
    const body = await response.json();
    if (!Array.isArray(body.features)) return [];
    const results: LocationResult[] = [];
    for (const feature of body.features) {
      const coordinates = feature?.geometry?.coordinates;
      const p = feature?.properties;
      if (!Array.isArray(coordinates) || coordinates.length !== 2 || !coordinates.every((v: unknown) => typeof v === 'number' && Number.isFinite(v)) || typeof p?.name !== 'string') continue;
      const [longitude,latitude] = coordinates;
      const approved = approvedRegion(longitude,latitude,regions);
      if (!approved) continue;
      const label = [...new Set([p.name,p.city,p.state,p.country].filter((v): v is string => typeof v === 'string' && !!v))].join(', ');
      results.push({label,longitude,latitude,region:approved});
    }
    return results;
  }));
  if (signal.aborted) return [];
  if (batches.every(b => b.status === 'rejected')) throw new Error('Location search unavailable. Choose a region or enter coordinates.');
  const unique = new Map<string,LocationResult>();
  for (const batch of batches) if (batch.status === 'fulfilled') for (const result of batch.value) unique.set(`${result.longitude},${result.latitude},${result.label}`,result);
  return [...unique.values()].slice(0,12);
}
