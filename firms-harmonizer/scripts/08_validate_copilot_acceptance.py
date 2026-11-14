"""Real-data acceptance matrix with full answers and explicit, reproducible checks.

Use --live to exercise real search/model providers. Passing measures these cases,
not universal correctness; source statements still require review against originals.
"""
from pathlib import Path
import argparse
import json
import os
import sys
from time import perf_counter
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')

CASES = [
 ('madrid_cause','por que sucedio ese incendio en madrid el 24 de julio de 2026','incident'),
 ('madrid_english','Why did the Madrid fire spread on 24 July 2026?','incident'),
 ('madrid_facts','What happened in Madrid on 24 July 2026?','event'),
 ('madrid_counts','How many detections in Madrid on 24 July 2026?','number'),
 ('madrid_power','Total FRP in Madrid on 24 July 2026','number'),
 ('madrid_energy','How many GJ in Madrid on 24 July 2026?','energy'),
 ('manaus_counts','Quantas deteccoes em Manaus em September 2024?','number'),
 ('careiro','How many fires in Careiro on 13 September 2024?','number'),
 ('gj_definition','¿Qué significa GJ?','definition'),
 ('pm25_unavailable','How much PM2.5 was emitted in Madrid in 2026?','unavailable'),
 ('impossible_date','How many detections in Madrid on 31 February 2026?','invalid'),
 ('help','What can you do?','help'),
]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'data/processed/copilot_acceptance.json')
    args=parser.parse_args()
    os.environ['USE_SYNTHETIC_CUBE']='0'
    os.environ['COPILOT_OFFLINE']='0' if args.live else '1'
    from fastapi.testclient import TestClient
    from backend.api.main import app
    from backend.api import fire_copilot as c
    from backend.api.schemas import ExplainSpikeRequest
    report={'mode':'live' if args.live else 'offline','cases':[],
        'limits':'Case-specific acceptance, not a guarantee about every possible question or independent certification of reports.'}
    with TestClient(app) as client:
        for key,q,kind in CASES:
            t=perf_counter();r=client.post('/api/explain-spike',json={'user_question':q});body=r.json()
            text=body.get('explanation_markdown','');scope=c.resolve_scope(ExplainSpikeRequest(user_question=q))
            checks={'http_ok':r.status_code==200,'nonempty':bool(text),'real':body.get('data_source')=='real',
                'links_safe':all(c.safe_url(x['url']) for x in body.get('citations',[]) if x.get('url'))}
            if kind in ('number','incident','event') and scope.coordinates and scope.start:
                from importlib.util import spec_from_file_location,module_from_spec
                spec=spec_from_file_location('independent_validation',ROOT/'scripts/06_validate_copilot.py');module=module_from_spec(spec);spec.loader.exec_module(module)
                n,power=module.independent_totals(scope)
                checks['independent_count']=f'**{n:,} satellite detection' in text
            if kind=='incident' and args.live:
                lead=text.split('### What the local data show')[0].lower()
                checks['answers_reported_spread']=body.get('physical_classification')=='REPORTED_INCIDENT_CONTEXT' and any(w in lead for w in ('wind','viento','temperatur','humidity'))
                checks['no_other_incident_as_answer']='burgohondo' not in lead
            if kind=='energy':checks['energy_computed']=' GJ**' in text
            if kind=='definition':checks['unit_conversion']='1,000' in text
            if kind=='unavailable':checks['no_substitute_counts']=body.get('physical_classification')=='DATA_NOT_AVAILABLE'
            if kind=='invalid':checks['invalid_explained']='invalid' in text.lower()
            checks['no_empty_or_invented_citations']=all(x['id'] in text for x in body.get('citations',[]))
            report['cases'].append({'id':key,'question':q,'elapsed_ms':round((perf_counter()-t)*1000),
                'checks':checks,'answer':text,'sources':[{k:x[k] for k in ('id','title','url','dataset_or_doi')} for x in body.get('citations',[])]})
            print(key, 'PASS' if all(checks.values()) else 'FAIL',checks,flush=True)
    report['passed']=sum(all(x['checks'].values()) for x in report['cases']);report['total']=len(CASES)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(f"{report['passed']}/{report['total']} passed; report: {args.output}")
    if report['passed']!=report['total']:raise SystemExit(1)

if __name__=='__main__':main()
