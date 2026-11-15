"""Publish terrestrial coverage indexes and a chronological threshold comparison."""
from pathlib import Path
from datetime import date
import json
import sys
import numpy as np
import h3.api.basic_int as h3

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.db.land_coverage import fractions,revision
from backend.core.coverage_policy import assess
from backend.db import queries,duckdb_engine


def main():
    registry = json.loads((ROOT/'data/regions.json').read_text(encoding='utf-8'))
    reports = {}
    for region,config in registry.items():
        w,s,e,n = config['bounds']
        coords = [[[w,s],[e,s],[e,n],[w,n],[w,s]]]
        r4,cells,_ = queries.get_hierarchical_h3_filter(coords)
        area = queries.polygon_area_km2(coords)
        daily = queries.fetch_aoi_aggregated_data(r4,cells,2000,2026,True,area).daily
        days = daily['epoch_day']
        output = ROOT/'data/processed/observation_coverage'/('land_'+region+'.npz')
        coverage = None
        if output.exists():
            with np.load(output,allow_pickle=False) as previous:
                if ('revision' in previous.files and str(previous['revision'])==revision(ROOT)
                    and int(previous['first'])==int(days[0]) and len(previous['fraction'])==len(days)
                    and np.array_equal(previous['cells'],np.array(sorted(cells),dtype=np.uint64))):
                    coverage = previous['fraction'].copy()
        if coverage is None:
            # Six recent years provide >=3 training years plus separate selection
            # and holdout years. The complete historical masks remain retained;
            # older coverage is unknown to this forecast experiment, never zero.
            first = max(int(days[0]),int(days[-1])-6*366+1)
            coverage = np.full(len(days),np.nan)
            coverage[first-int(days[0]):] = fractions(ROOT,cells,first,int(days[-1]))
        temporary = output.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            np.savez_compressed(stream,cells=np.array(sorted(cells),dtype=np.uint64),first=int(days[0]),fraction=coverage,revision=revision(ROOT))
        temporary.replace(output)
        values = np.where(daily['observation_known'],daily['observed_energy_mj']/area,np.nan)
        dates = np.datetime64('1970-01-01')+days.astype('timedelta64[D]')
        report = assess(dates,values,coverage)
        report.update(known_land_denominator_days=int(np.isfinite(coverage).sum()),
            experiment_coverage_start=str(dates[max(0,len(days)-6*366)]),
            mean_supported_land_fraction=float(np.nanmean(coverage)) if np.isfinite(coverage).any() else None,
            method='Qualified-cell area proxy, union across sensors; preceding-year measured land/water fractions; no cloud filling or energy upscaling')
        reports[region] = report
        destination = ROOT.parent/'docs/verification/2026-11-15-all-nighter/coverage-policy.json'
        destination.write_text(json.dumps(reports,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(region,report['selected_threshold'],report['mean_supported_land_fraction'],flush=True)


if __name__ == '__main__':
    main()
