"""Use measured annual MCD12Q1 classes, never nominal regional biomes, for emissions."""
import h3.api.basic_int as h3i
import numpy as np
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

from backend.core.emissions import factor_stats, pm25_kg


def estimate(root, cells, years, energy, index, n):
    result = np.full(n, np.nan)
    path = root / 'data/lookup/igbp_cells.parquet'
    if not path.is_file():
        return result, result.copy()
    schema = pq.read_schema(path)
    if not {'year','h3_r7','igbp_biome'}.issubset(schema.names) or b'MCD12Q1' not in (schema.metadata or {}).get(b'source', b''):
        return result, result.copy()
    requested = pa.table({'h3_r7': pa.array(cells, pa.uint64()), 'year': pa.array(years)}).group_by(['h3_r7','year']).aggregate([])
    fraction = 'source.dominant_fraction' if 'dominant_fraction' in schema.names else '1.0'
    with duckdb.connect(config={'threads': 1}) as cursor:
        cursor.register('requested_emission_cells', requested)
        sql = 'SELECT source.h3_r7, source.year, source.igbp_biome, ' + fraction + ' AS dominant_fraction FROM read_parquet(?) source SEMI JOIN requested_emission_cells USING (h3_r7,year)'
        rows = cursor.execute(sql, [str(path)]).to_arrow_table().to_pylist()
    lookup = {(row['h3_r7'], row['year']): row['igbp_biome'] for row in rows if row['dominant_fraction'] >= .5}
    latitude = {int(cell): h3i.cell_to_latlng(int(cell))[0] for cell in np.unique(cells)}
    stats = [factor_stats(lookup.get((int(cell), int(year))), latitude[int(cell)])
             for cell, year in zip(cells, years)]
    factors = np.array([s[0] if s else np.nan for s in stats])
    spread = np.array([s[1] if s else np.nan for s in stats])
    known = np.isfinite(factors)
    missing = np.bincount(index, weights=(~known) & (energy > 0), minlength=n) > 0
    total = np.bincount(index, weights=np.where(known, pm25_kg(energy, factors), 0), minlength=n)
    present = np.bincount(index, weights=energy > 0, minlength=n) > 0
    result[present & ~missing] = total[present & ~missing]
    variance = np.zeros(n)
    for value in np.unique(factors[known]):
        chosen = known & (factors == value)
        biomass = np.bincount(index, weights=np.where(chosen, energy * .368, 0), minlength=n)
        sd = float(spread[chosen][0])
        variance += (biomass * sd / 1000)**2
    sd_result = np.where(np.isfinite(result), np.sqrt(variance + (result * .015 / .368)**2), np.nan)
    return result, sd_result
