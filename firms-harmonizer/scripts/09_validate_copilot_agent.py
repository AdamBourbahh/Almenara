"""Live Groq tool/RAG acceptance. Uses configured credentials, never synthetic data.

Run one case per --question to inspect free-tier quota independently. Responses and
actual model-selected tools are saved even when a case fails. A fallback is not
counted as a successful live-model answer.
"""
from pathlib import Path
import argparse,json,os,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT/'.env')
os.environ['USE_SYNTHETIC_CUBE']='0'
os.environ['COPILOT_OFFLINE']='0'
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import copilot_agent as agent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--question',action='append')
    parser.add_argument('--output',type=Path,default=ROOT/'data/processed/copilot_agent.json')
    args=parser.parse_args()
    cases=args.question or ['the reason of the fire is known?','How much energy in GJ was released here?', 'What does FRP mean?']
    records=[]
    with TestClient(app) as client:
        for question in cases:
            trace=[]
            original=agent.turn
            def recorded(*a,**kw):
                response=original(*a,**kw)
                trace.extend(c['function']['name'] for c in response.get('tool_calls',[]))
                return response
            agent.turn=recorded
            try:
                response=client.post('/api/explain-spike',json={'region_name':'Selected map area',
                    'aoi':{'coordinates':[[[-4.8,40.2],[-4.15,40.2],[-4.15,40.58],[-4.8,40.58],[-4.8,40.2]]]},
                    'period_start':'2026-07-24','period_end':'2026-07-24','user_question':question})
                body=response.json()
                passed=response.status_code==200 and body.get('model_used','').startswith('groq-agent/') and bool(body.get('citations'))
                records.append({'question':question,'tools':trace,'passed':passed,'response':body})
                print(question,'PASS' if passed else 'FAIL',trace,flush=True)
            finally:
                agent.turn=original
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(records,indent=2,ensure_ascii=False))
    if not all(r['passed'] for r in records):
        raise SystemExit(1)

if __name__=='__main__':
    main()
