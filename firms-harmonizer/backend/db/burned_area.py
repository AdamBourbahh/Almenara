"""Independent MCD64A1 totals, including burned cells absent from the FIRMS cube."""
import json

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry import Polygon, box
from shapely.ops import unary_union


def annual_totals(root, cursor, coords, cells, years):
    path = root / 'data/lookup/cell_day_ancillary.parquet'
    unavailable = np.full(len(years), np.nan)
    if not path.is_file():
        return unavailable
    metadata = pq.read_schema(path).metadata or {}
    complete = json.loads(metadata.get(b'complete_years', b'{}'))
    registry = json.loads((root / 'data/regions.json').read_text(encoding='utf-8'))
    polygon = Polygon(coords[0], coords[1:])
    selected = [name for name, region in registry.items() if polygon.intersects(box(*region['bounds']))]
    if not selected or not unary_union([box(*registry[name]['bounds']) for name in selected]).covers(polygon):
        return unavailable
    valid_years = set.intersection(*(set(complete.get(name, [])) for name in selected))
    if not valid_years:
        return unavailable
    cursor.register('burned_aoi', pa.table({'h3_r7': pa.array(cells, pa.uint64())}))
    try:
        rows = cursor.execute('''SELECT year(acq_date), sum(burned_area_ha_mcd64)
            FROM read_parquet(?) WHERE h3_r7 IN (SELECT h3_r7 FROM burned_aoi)
            GROUP BY year(acq_date)''', [str(path)]).fetchall()
    finally:
        cursor.unregister('burned_aoi')
    totals = dict(rows)
    return np.array([float(totals.get(int(year), 0.)) if int(year) in valid_years else np.nan for year in years])
