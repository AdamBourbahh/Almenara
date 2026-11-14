"""Exercise real-data Fire Copilot requests, with optional live model/search calls.

Run from firms-harmonizer: python scripts/06_validate_copilot.py [--live]
The default verifies deterministic offline behavior. Outputs preserve the complete
answers and citations for review; no event answer is hardcoded in the assistant.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
import pyarrow as pa
from fastapi.testclient import TestClient

load_dotenv(ROOT / '.env')

CASES = [
    ('madrid_2026', '¿Qué pasó en el incendio de Madrid del 24 de julio de 2026?'),
    ('sierra_oeste_2026', 'What happened near San Martín de Valdeiglesias on 24 July 2026?'),
    ('careiro_2024', 'Investigate the fires near Careiro, Amazonas on 13 September 2024.'),
    ('autazes_2023', 'What happened near Autazes, Amazonas on 9 October 2023?'),
    ('manaus_month', 'Which days had the most detections near Manaus in September 2024?'),
]


def independent_totals(scope):
    """A separate scalar SQL aggregate cross-checks each returned numerical summary."""
    from backend.db import duckdb_engine, queries
    r4, r7, _ = queries.get_hierarchical_h3_filter(scope.coordinates)
    with duckdb_engine.get_db_cursor() as cursor:
        cursor.register('validation_r4', pa.table({'cell': pa.array(r4, type=pa.uint64())}))
        cursor.register('validation_r7', pa.table({'cell': pa.array(r7, type=pa.uint64())}))
        count, power = cursor.execute('''SELECT count(*), coalesce(sum(frp),0)
            FROM read_parquet(?) WHERE is_center AND acq_date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
            AND h3_r4 IN (SELECT cell FROM validation_r4) AND h3_r7 IN (SELECT cell FROM validation_r7)''',
            [str(ROOT / 'data/processed/staged_firms.parquet'), scope.start, scope.end]).fetchone()
    return int(count), float(power)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Allow configured model/search providers')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/copilot_validation.json')
    args = parser.parse_args()
    os.environ['USE_SYNTHETIC_CUBE'] = '0'
    os.environ['COPILOT_OFFLINE'] = '0' if args.live else '1'
    from backend.api import fire_copilot
    from backend.api.main import app
    from backend.api.schemas import ExplainSpikeRequest, ExplainSpikeResponse
    from backend.db import duckdb_engine

    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'mode': 'live' if args.live else 'offline', 'cases': [],
              'limits': 'Numerical and contract checks are automated. Event narrative quality and source correspondence require human review. Study envelopes are not municipalities, incident perimeters or proof that a detection belongs to a reported fire.'}
    with TestClient(app) as client:
        if duckdb_engine.data_source() != 'real':
            raise RuntimeError('Real cube and staging are required for event validation.')
        for key, question in CASES:
            request = ExplainSpikeRequest(region_name='Chilecito, Argentina', user_question=question)
            scope = fire_copilot.resolve_scope(request)
            expected_count, expected_power = independent_totals(scope)
            start = perf_counter()
            response = client.post('/api/explain-spike', json=request.model_dump())
            response.raise_for_status()
            result = ExplainSpikeResponse.model_validate(response.json())
            text = result.explanation_markdown
            checks = {
                'real_provenance': result.data_source == 'real',
                'count_matches_archive': f'**{expected_count:,} satellite detections**' in text,
                'power_matches_archive': f'**{expected_power:,.2f} MW**' in text,
                'requested_date_present': scope.start in text,
                'no_stale_chilecito_scope': 'Chilecito' not in text,
                'not_labeled_extreme_from_counts': result.physical_classification != 'EXTREME_VEGETATION_FIRE',
                'sources_linked': all(c.url and fire_copilot.safe_url(c.url) for c in result.citations),
            }
            report['cases'].append({'id': key, 'question': question, 'elapsed_ms': round((perf_counter()-start)*1000, 1),
                'expected_detections': expected_count, 'expected_summed_frp_mw': round(expected_power, 2),
                'checks': checks, 'response': result.model_dump()})
            print(f"{key}: {'PASS' if all(checks.values()) else 'FAIL'}; {expected_count:,} detections; {result.model_used}; web={result.web_search_used}", flush=True)
        history = [{'role': 'user', 'content': CASES[0][1]},
                   {'role': 'assistant', 'content': report['cases'][0]['response']['explanation_markdown'][:6000]}]
        followup = client.post('/api/explain-spike', json={'region_name': 'Chilecito',
            'user_question': 'And on the next day?', 'conversation': history})
        followup.raise_for_status()
        report['followup'] = followup.json()
        report['followup_correct_date'] = '2026-07-25' in report['followup']['explanation_markdown']
    report['passed'] = all(all(case['checks'].values()) for case in report['cases']) and report['followup_correct_date']
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(f"Saved reviewable answers to {args.output}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
