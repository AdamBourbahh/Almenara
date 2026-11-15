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
from datetime import date

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.update(USE_SYNTHETIC_CUBE='0',COPILOT_OFFLINE='0',NRT_POLLING='0',AUTO_SYNC='0',REQUEST_RATE_MULTIPLIER='10000')
import duckdb
import h3
import numpy as np
import pyarrow.parquet as pq
from scipy.stats import f as f_distribution
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import copilot_agent as agent

ZONES=[('Arid Argentina','87b254925ffffff','2022-12-15','2023-01-15',True),
       ('Amazon basin','878af68f2ffffff','2023-01-01','2023-12-31',True),
       ('Florida','8744f690cffffff','2023-01-01','2023-12-31',True),
       ('Atlantic Iberia','87185ba0cffffff','2023-01-01','2023-12-31',True),
       ('Mediterranean Iberia','873915d61ffffff','2023-01-01','2023-12-31',True),
       ('Published persistent-source candidate','873954066ffffff','2013-01-01','2013-12-31',False)]
HOLDOUT=('Northern Africa holdout','873828d5affffff','2023-01-01','2023-12-31',True)
QUESTION=('Audit the selected area: report mapped FRE in GJ, raw and harmonized Chow F and p, '
 'raw and harmonized Wasserstein W1, latest von Mises peak DOY, kappa and width, and reconstructed and unknown days. '
 'Use local measurements only. State unavailable diagnostics explicitly. Do not infer ignition, cloudiness or vegetation from missing observations.')


def independent_clear_days(cell,start,end):
    """Decode measured packed mask bits for one cell without coverage adapters."""
    lat,lon=h3.cell_to_latlng(cell)
    registry=json.loads((ROOT/'data/regions.json').read_text(encoding='utf-8'))
    prefixes=[name for name,r in registry.items() if r['bounds'][0]<=lon<=r['bounds'][2]
              and r['bounds'][1]<=lat<=r['bounds'][3]]
    first,last=[(date.fromisoformat(d)-date(1970,1,1)).days for d in (start,end)]
    groups={}
    for prefix in prefixes:
        for path in (ROOT/'data/processed/observation_coverage').glob(prefix+'_*.parquet'):
            meta=pq.read_schema(path).metadata or {}
            days=json.loads(meta.get(b'days',b'[]'))
            if not days or min(days)>last or max(days)<first:
                continue
            row=pq.read_table(path).to_pylist()[0]
            cells=np.frombuffer(row['cells'],dtype=np.uint64)
            index=int(np.searchsorted(cells,int(cell,16)))
            if index>=len(cells) or int(cells[index])!=int(cell,16):
                continue
            clear=np.unpackbits(np.frombuffer(row['clear_bits'],dtype=np.uint8).reshape(len(days),-1),axis=1,count=len(cells))[:,index]
            fire=np.unpackbits(np.frombuffer(row['fire_bits'],dtype=np.uint8).reshape(len(days),-1),axis=1,count=len(cells))[:,index]
            satellite=meta[b'satellite'].decode()
            composite=meta.get(b'granule',path.name.encode()).decode().split('.')[1]
            group=groups.setdefault((satellite,composite),[])
            group.append({d:(bool(c),bool(f)) for d,c,f in zip(days,clear,fire)})
    zero=set()
    for tiles in groups.values():
        days=set.union(*(set(t) for t in tiles))
        for d in days:
            if first<=d<=last and all(t.get(d,(False,False))[0] for t in tiles) and not any(t.get(d,(False,False))[1] for t in tiles):
                zero.add(d)
    return zero


def independent_statistics(con,data,cell,exclude,start,end):
    """Independent SQL input and statistical arithmetic; no production helpers."""
    rows=con.execute('''select epoch_day,raw_modis_cnt+raw_viirs_cnt,
        obs_terra_fre,obs_aqua_fre,obs_viirs_fre,gap_status_mask
        from read_parquet(?) where h3_r7=? and (not ? or industrial_prob<0.75)''',
        [str(ROOT/'data/processed/fire_cube.parquet'),int(cell,16),exclude]).fetchall()
    observed={int(r[0]):r for r in rows}
    series=[c for c in data['calendar_series'] if not c['is_forecast']]
    years=np.array([c['year'] for c in series])
    raw=[]
    density=[]
    unknown=0
    evidenced_gaps=0
    clear=independent_clear_days(cell,start,end)
    for c in series:
        epoch=(date.fromisoformat(c['date'])-date(1970,1,1)).days
        row=observed.get(epoch)
        vals=[v for v in row[2:5] if v is not None] if row else []
        raw.append(row[1] if row else 0)
        density.append(math.fsum(vals)/len(vals)*h3.cell_area(cell,unit='km^2')/data['aoi_area_km2'] if vals else 0.)
        if start<=c['date']<=end:
            unknown+=not vals and epoch not in clear
            evidenced_gaps+=bool(row and row[5] and not vals)
    # These selected cases have observed gap flags but no missing-energy days
    # eligible for reconstruction. Refuse to claim an independent RTS oracle.
    if evidenced_gaps:
        raise ValueError('This oracle does not independently reproduce RTS gap reconstruction.')
    raw=np.array(raw,dtype=float)
    density=np.array(density)
    assert np.allclose(raw,[c['raw_hotspot_count'] for c in series],rtol=0,atol=0)
    assert np.allclose(density,[c['harmonized_fre_mj_km2'] for c in series],rtol=1e-12,atol=1e-10)
    unique,counts=np.unique(years,return_counts=True)
    complete=[int(y) for y,n in zip(unique,counts) if n==(date(int(y)+1,1,1)-date(int(y),1,1)).days]
    keep=np.isin(years,complete)
    def chow(values):
        annual=np.array([values[years==y].mean() for y in complete])
        yy=np.array(complete,dtype=float)
        design=np.column_stack((np.ones(len(yy)),yy-yy.mean()))
        annual/=max(float(np.max(np.abs(annual))),1.)
        pre=yy<2012
        def rss(mask):
            a,b=design[mask],annual[mask]
            residual=b-a@np.linalg.lstsq(a,b,rcond=None)[0]
            return float(residual@residual)
        pooled=rss(np.ones(len(yy),dtype=bool))
        split=rss(pre)+rss(~pre)
        tolerance=64*len(yy)*np.finfo(float).eps**2
        if pooled<=tolerance:
            return 0.,1.
        statistic=max(0.,(pooled-split)/2)/max(split/(len(yy)-4),tolerance)
        return statistic,float(f_distribution.sf(statistic,2,len(yy)-4))
    def w1(values):
        values=values[keep]
        if values.mean()<=0:
            return 0.
        a=np.sort(values[years[keep]<2012]/values.mean())
        b=np.sort(values[years[keep]>=2012]/values.mean())
        support=np.sort(np.concatenate((a,b)))
        return float(np.sum(np.abs(np.searchsorted(a,support[:-1],side='right')/len(a)
            -np.searchsorted(b,support[:-1],side='right')/len(b))*np.diff(support)))
    cr,ch=chow(raw),chow(density)
    supported=[int(y) for y in np.unique(years) if density[years==y].sum()>0]
    fitted_year=max(supported)
    last=years==fitted_year
    weights=density[last]
    days=np.array([c['doy'] for c in series])[last]
    mu,kappa=1.,0.
    if weights.sum()>0:
        angles=days*2*math.pi/365.25
        sine=math.fsum(w*math.sin(a) for w,a in zip(weights,angles))/weights.sum()
        cosine=math.fsum(w*math.cos(a) for w,a in zip(weights,angles))/weights.sum()
        r=min(1.,math.hypot(sine,cosine))
        if r>1e-12:
            mu=max(1.,min(365.25,(math.atan2(sine,cosine)%(2*math.pi))*365.25/(2*math.pi)))
            kappa=2*r+r**3+5*r**5/6 if r<.53 else -.4+1.39*r+.43/(1-r) if r<.85 else 1/max(1e-4,r**3-4*r*r+3*r)
    return dict(audit_metrics=dict(chow_test_f_stat_raw=cr[0],chow_test_p_val_raw=cr[1],
        chow_test_f_stat_harm=ch[0],chow_test_p_val_harm=ch[1],wasserstein_w1_raw=w1(raw),wasserstein_w1_harm=w1(density)),
        phenology=dict(year=fitted_year,peak_doy_mu=mu,concentration_kappa=kappa,
            season_width_days=min(365.,365.25/math.sqrt(max(.15,kappa)))),
        reconstructed_days=0,unknown_days=unknown,input_rows=len(rows))


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
                confidence_level='nominal',exclude_industrial_flaring=exclude,enable_kalman_gap_filling=True,
                user_question=QUESTION)
            analysis=client.post('/api/analyze',json=dict(aoi=aoi,start_year=2000,end_year=2026,forecast_days=0,
                confidence_level='nominal',exclude_industrial_flaring=exclude,enable_kalman_gap_filling=True))
            data=analysis.json()
            rows=con.execute('''select obs_terra_fre,obs_aqua_fre,obs_viirs_fre from read_parquet(?)
                where h3_r7=? and epoch_day between date_diff('day',date '1970-01-01',cast(? as date))
                and date_diff('day',date '1970-01-01',cast(? as date)) and (not ? or industrial_prob<0.75)''',
                [str(ROOT/'data/processed/fire_cube.parquet'),int(cell,16),start,end,exclude]).fetchall()
            direct=math.fsum(math.fsum(v for v in row if v is not None)/sum(v is not None for v in row)
                for row in rows if any(v is not None for v in row))*h3.cell_area(cell,unit='km^2')/1000
            selected=[c for c in data.get('calendar_series',[]) if start<=c['date']<=end and not c['is_forecast']]
            diagnostic_keys=('chow_test_f_stat_raw','chow_test_p_val_raw','chow_test_f_stat_harm',
                'chow_test_p_val_harm','wasserstein_w1_raw','wasserstein_w1_harm')
            phenology_keys=('year','peak_doy_mu','peak_date_label','concentration_kappa','season_width_days')
            supported_phenology=[p for p in data.get('phenology_by_year',[]) if p['concentration_kappa']>1e-12 and p['total_annual_fre_gj']>0]
            reference=dict(mapped_energy_gj=direct,start=start,end=end,
                audit_metrics=({k:data['audit_metrics'][k] for k in diagnostic_keys} if data.get('audit_metrics') else None),
                phenology=({k:supported_phenology[-1][k] for k in phenology_keys} if supported_phenology else None),
                reconstructed_days=sum(c['is_gap_filled'] for c in selected),
                unknown_days=sum(c['observation_status']=='unknown' for c in selected))
            oracle=independent_statistics(con,data,cell,exclude,start,end)
            for key,value in oracle['audit_metrics'].items():
                assert math.isclose(value,reference['audit_metrics'][key],rel_tol=1e-10,abs_tol=1e-10),(label,key,value,reference['audit_metrics'][key])
            for key,value in oracle['phenology'].items():
                assert math.isclose(value,reference['phenology'][key],rel_tol=1e-10,abs_tol=1e-10),(label,key)
            assert oracle['reconstructed_days']==reference['reconstructed_days']
            assert oracle['unknown_days']==reference['unknown_days']
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
                analysis_status=analysis.status_code,reference=reference,independent_oracle=oracle,response=body,model_calls=trace,
                fallback=fallback,match_data=match,model_ok=model_ok,semantic_review='pending',
                passed=response.status_code==200 and analysis.status_code==200 and data.get('data_source')=='real' and match and model_ok and not fallback)
            records.append(record)
            args.output.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            print(label,model,'MATCH',match,'PASS' if record['passed'] else 'FAIL',flush=True)
    raise SystemExit(0 if len(records)==len(zones) and all(r['passed'] for r in records) else 1)


if __name__=='__main__':
    main()
