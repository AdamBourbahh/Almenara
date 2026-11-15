"""Live six-zone regression and a fresh holdout; real data, no mocked provider.

The credential is read from the process environment only. Every attempted round
is retained, including failures. Statistical reference values come from the real
scientific pipeline; mapped energy is independently integrated from Parquet SQL.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(USE_SYNTHETIC_CUBE='0',COPILOT_OFFLINE='0',NRT_POLLING='0',AUTO_SYNC='0',REQUEST_RATE_MULTIPLIER='10000')
import duckdb
import h3
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import copilot_agent as agent

ZONES=[('Arid Argentina','87b254925ffffff','2022-12-15','2023-01-15',True),
       ('Amazon basin','878af68f2ffffff','2023-01-01','2023-12-31',True),
       ('Florida','8744f690cffffff','2023-01-01','2023-12-31',True),
       ('Atlantic Iberia','87185ba0cffffff','2023-01-01','2023-12-31',True),
       ('Mediterranean Iberia','873915d61ffffff','2023-01-01','2023-12-31',True),
       ('Published persistent-source candidate','873954066ffffff','2023-01-01','2023-12-31',False)]
HOLDOUT=('Northern Africa holdout','873828d5affffff','2023-01-01','2023-12-31',True)
QUESTION=('Audit the selected area: report mapped FRE in GJ, raw and harmonized Chow F and p, '
 'raw and harmonized Wasserstein W1, latest von Mises peak DOY, kappa and width, and reconstructed and unknown days. '
 'Use local measurements only. State unavailable diagnostics explicitly. Do not infer ignition, cloudiness or vegetation from missing observations.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--reviewed-six',type=Path)
    parser.add_argument('--holdout-cell',default=HOLDOUT[1])
    args=parser.parse_args()
    if not os.getenv('GEMINI_API_KEY'):
        raise SystemExit('GEMINI_API_KEY must be provided in the process environment.')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    records=[]
    original=agent.turn
    zones=ZONES
    if args.reviewed_six:
        six=json.loads(args.reviewed_six.read_text(encoding='utf-8'))
        if len(six)!=6 or not all(r['passed'] and r['semantic_review']=='pass' for r in six):
            raise SystemExit('The six zones must pass numerical and semantic review before a fresh holdout.')
        if args.holdout_cell in {r['h3'] for r in six}:
            raise SystemExit('Holdout must use a new cell.')
        zones=[(HOLDOUT[0],args.holdout_cell,*HOLDOUT[2:])]
    with TestClient(app) as client,duckdb.connect() as con:
        for i,(label,cell,start,end,exclude) in enumerate(zones):
            ring=[[lon,lat] for lat,lon in h3.cell_to_boundary(cell)]
            aoi={'coordinates':[ring+[ring[0]]]}
            payload=dict(aoi=aoi,region_name=label,prefer_map_context=True,period_start=start,period_end=end,
                confidence_level='nominal',exclude_industrial_flaring=exclude,enable_kalman_gap_filling=False,
                user_question=QUESTION)
            analysis=client.post('/api/analyze',json=dict(aoi=aoi,start_year=2000,end_year=2026,forecast_days=14,
                confidence_level='nominal',exclude_industrial_flaring=exclude,enable_kalman_gap_filling=False))
            data=analysis.json()
            rows=con.execute('''select obs_terra_fre,obs_aqua_fre,obs_viirs_fre from read_parquet(?)
                where h3_r7=? and epoch_day between date_diff('day',date '1970-01-01',cast(? as date))
                and date_diff('day',date '1970-01-01',cast(? as date)) and (not ? or industrial_prob<0.75)''',
                [str(ROOT/'data/processed/fire_cube.parquet'),int(cell,16),start,end,exclude]).fetchall()
            direct=math.fsum(math.fsum(v for v in row if v is not None)/sum(v is not None for v in row)
                for row in rows if any(v is not None for v in row))*h3.cell_area(cell,unit='km^2')/1000
            selected=[c for c in data.get('calendar_series',[]) if start<=c['date']<=end and not c['is_forecast']]
            reference=dict(mapped_energy_gj=direct,start=start,end=end,audit_metrics=data.get('audit_metrics'),
                phenology=(data.get('phenology_by_year') or [None])[-1],
                reconstructed_days=sum(c['is_gap_filled'] for c in selected),
                unknown_days=sum(c['observation_status']=='unknown' for c in selected))
            trace=[]
            def recorded(*a,**kw):
                before=time.perf_counter()
                try:
                    result=original(*a,**kw)
                    trace.append(dict(ms=round((time.perf_counter()-before)*1000),response=result))
                    return result
                except Exception as exc:
                    trace.append(dict(ms=round((time.perf_counter()-before)*1000),error=type(exc).__name__))
                    raise
            agent.turn=recorded
            before=time.perf_counter()
            try:
                response=client.post('/api/explain-spike',json=payload)
            finally:
                agent.turn=original
            body=response.json()
            blocks=re.findall(r'```json\s*(.*?)\s*```',body.get('explanation_markdown',''),re.S)
            actual=json.loads(blocks[-1]) if blocks else None
            def equal(a,b):
                if isinstance(a,dict) and isinstance(b,dict):
                    return a.keys()==b.keys() and all(equal(a[k],b[k]) for k in a)
                if isinstance(a,(float,int)) and isinstance(b,(float,int)):
                    return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-10)
                return a==b
            match=actual is not None and equal(reference,actual)
            model=body.get('model_used','')
            fallback='offline' in model or 'deterministic' in model
            model_ok=model.startswith('gemini-agent/')
            # A numeric match is necessary, never sufficient for a hallucination
            # verdict. Preserve prose for a separate semantic review.
            record=dict(zone=label,h3=cell,polygon_sha256=hashlib.sha256(json.dumps(aoi,sort_keys=True).encode()).hexdigest(),
                request=payload,status=response.status_code,elapsed_ms=round((time.perf_counter()-before)*1000),
                analysis_status=analysis.status_code,reference=reference,response=body,model_calls=trace,
                fallback=fallback,match_data=match,model_ok=model_ok,semantic_review='pending',
                passed=response.status_code==200 and analysis.status_code==200 and data.get('data_source')=='real' and match and model_ok and not fallback)
            records.append(record)
            args.output.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(label,model,'MATCH',match,'PASS' if record['passed'] else 'FAIL',flush=True)
    raise SystemExit(0 if len(records)==len(zones) and all(r['passed'] for r in records) else 1)


if __name__=='__main__':
    main()
