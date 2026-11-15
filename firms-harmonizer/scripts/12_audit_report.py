"""Real-cube acceptance: canonical API metrics versus independent per-cell integrals."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def generate():
    import h3
    import numpy as np
    from fastapi.testclient import TestClient
    from backend.api.cache import ANALYZE_CACHE
    from backend.api.main import app
    from backend.db import duckdb_engine, queries
    registry = json.loads((ROOT / 'data/regions.json').read_text(encoding='utf-8'))
    results = []
    with TestClient(app) as client:
        for key, region in registry.items():
            w, s, e, n = region['bounds']
            coords = [[[w, s], [e, s], [e, n], [w, n], [w, s]]]
            request = {'aoi': {'type': 'Polygon', 'coordinates': coords}, 'start_year': 2000, 'forecast_days': 14}
            ANALYZE_CACHE.clear()
            started = perf_counter()
            response = client.post('/api/analyze', json=request)
            response.raise_for_status()
            wall_ms = (perf_counter() - started) * 1000
            data = response.json()
            r4, r7, _ = queries.get_hierarchical_h3_filter(coords)
            with duckdb_engine.get_db_cursor() as cursor:
                table = queries.query_aoi_rows(cursor, r4, r7, 2000, 2026)
            area = {int(c): h3.cell_area(format(int(c), 'x'), unit='km^2') for c in set(table['h3_r7'].to_pylist())}
            independent = {}
            for row in table.to_pylist():
                if row['industrial_prob'] >= .75:
                    continue
                values = [row[c] for c in queries.OBS_COLUMNS if row[c] is not None]
                if values:
                    energy = sum(values) / len(values) * area[row['h3_r7']]
                    day = str(queries.EPOCH + np.timedelta64(row['epoch_day'], 'D'))
                    independent[day] = independent.get(day, 0.) + energy
            observed = [day for day in data['calendar_series'] if not day['is_gap_filled']]
            api_mj = sum(day['harmonized_fre_mj_km2'] * data['aoi_area_km2'] for day in observed)
            expected_mj = sum(independent.get(day['date'], 0.) for day in observed)
            if not np.isclose(api_mj, expected_mj, rtol=1e-10, atol=1e-4):
                raise AssertionError(f'{key}: energy integral differs from independent per-cell sum')
            biomass = sum(day['biomass_burned_tonnes'] for day in data['calendar_series'])
            energy_mj = sum(day['harmonized_fre_mj_km2'] * data['aoi_area_km2'] for day in data['calendar_series'])
            if not np.isclose(biomass, energy_mj * .368 / 1000, rtol=1e-10):
                raise AssertionError(f'{key}: biomass unit conversion differs')
            def cached_request(_):
                r = client.post('/api/analyze', json=request)
                r.raise_for_status()
                return r.json()['audit_metrics']['total_biomass_burned_kt']
            with ThreadPoolExecutor(max_workers=3) as pool:
                repeated = list(pool.map(cached_request, range(3)))
            if not all(np.isclose(value, biomass / 1000) for value in repeated):
                raise AssertionError(f'{key}: concurrent analyses disagree')
            statuses = {}
            for day in data['calendar_series']:
                statuses[day['observation_status']] = statuses.get(day['observation_status'], 0) + 1
            results.append(dict(region=key, data_source=data['data_source'], aoi_area_km2=data['aoi_area_km2'],
                observed_energy_gj=api_mj / 1000, independent_energy_gj=expected_mj / 1000,
                biomass_kt=biomass / 1000, daily_status_counts=statuses, audit=data['audit_metrics'],
                cold_http_ms=wall_ms, json_bytes=len(response.content), gzip_bytes=int(response.headers.get('content-length', 0)),
                first_date=data['calendar_series'][0]['date'], last_date=data['calendar_series'][-1]['date'],
                forecast_validation=data['forecast_validation'], forecast_unavailable_reason=data['forecast_unavailable_reason']))
            results[-1]['pm25_estimated_days'] = sum(day['pm25_emitted_kg'] is not None and day['pm25_emitted_kg'] > 0
                                                    for day in data['calendar_series'])
            print(f'{key}: per-cell integral PASS, biomass {biomass / 1000:,.3f} kt, {statuses}', flush=True)
    return dict(generated_utc=datetime.now(timezone.utc).isoformat(),
        method='Independent cell-area integrals, unit conversions, concurrent HTTP requests; scientific gates reported unchanged', regions=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT.parent / 'docs/verification/2026-11-15-all-nighter/report.json')
    args = parser.parse_args()
    report = generate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
