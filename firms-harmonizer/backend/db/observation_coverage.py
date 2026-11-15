"""Measured fire-mask coverage, separate from the sparse detection cube."""
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

SENSOR_CHANNELS = {'Terra': 0, 'Aqua': 1, 'SNPP': 2, 'NOAA-20': 2, 'NOAA-21': 2}


def apply_coverage(cur, root: Path, cells: list[int], daily: dict, area_km2: float, return_sensors=False):
    """Return complete observed-zero days; partial coverage never establishes zero.

    Granule summaries contain clear/fire/unknown areas. A region-day is complete
    only if every selected cell has >=95% valid coverage for at least one sensor.
    Gaps or absent shards remain unknown. Coverage cannot create fire detections.
    """
    n = len(daily['epoch_day'])
    zero = np.zeros(n, dtype=bool)
    sensors = np.zeros(n, dtype=np.int64)
    complete = np.zeros(n, dtype=bool)
    directory = root / 'data/processed/observation_coverage'
    if not n or not directory.is_dir() or not list(directory.glob('*.parquet')):
        return (zero, sensors, complete) if return_sensors else zero
    if (pq.read_schema(next(directory.glob('*.parquet'))).metadata or {}).get(b'encoding') == b'packed-v1':
        from backend.db.packed_coverage import read_selected
        codes, known = read_selected(str(root), directory.stat().st_mtime_ns, tuple(sorted(cells)),
                                    int(daily['epoch_day'][0]), int(daily['epoch_day'][-1]))
        sensors, complete = codes.copy(), known > 0
        zero = sensors > 0
        return (zero, sensors, complete) if return_sensors else zero
    cur.register('coverage_aoi', pa.table({'h3_r7': pa.array(cells, pa.uint64())}))
    try:
        rows = cur.execute('''WITH sensor_cell AS (
            SELECT epoch_day, h3_r7, satellite,
                   sum(clear_area_km2) AS clear_area, sum(fire_area_km2) AS fire_area,
                   sum(sampled_area_km2) AS sampled_area,
                   max(cell_area_km2) AS area
            FROM read_parquet(?) WHERE h3_r7 IN (SELECT h3_r7 FROM coverage_aoi)
            AND epoch_day BETWEEN ? AND ? GROUP BY epoch_day, h3_r7, satellite
        ) SELECT epoch_day, satellite,
                 count(*) FILTER (WHERE clear_area >= 0.95 * sampled_area AND sampled_area >= 0.5 * area),
                 sum(fire_area) FROM sensor_cell GROUP BY epoch_day, satellite''', [str(directory / '*.parquet'),
                int(daily['epoch_day'][0]), int(daily['epoch_day'][-1])]).fetchall()
    finally:
        cur.unregister('coverage_aoi')
    bits = {'Terra': 1, 'Aqua': 2, 'SNPP': 4, 'NOAA-20': 8, 'NOAA-21': 16}
    for epoch, satellite, count, fire in rows:
        if count == len(cells):
            index = int(epoch) - int(daily['epoch_day'][0])
            complete[index] = True
            if fire == 0:
                zero[index] = True
                sensors[index] |= bits[satellite]
    return (zero, sensors, complete) if return_sensors else zero
