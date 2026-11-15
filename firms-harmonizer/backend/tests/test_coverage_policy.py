from importlib import import_module
from datetime import date
import json
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import h3.api.basic_int as h3

from backend.core import coverage_policy
from backend.db.land_coverage import fractions,load,revision


def test_union_of_sensors_excludes_measured_water_and_uses_previous_year(tmp_path,monkeypatch):
    from backend.db.duckdb_engine import ROOT
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    writer = import_module('09_fetch_observation_coverage').write_summary
    masks = tmp_path/'data/processed/observation_coverage'
    masks.mkdir(parents=True)
    land = tmp_path/'data/cache/land_cover'
    land.mkdir(parents=True)
    (tmp_path/'data/regions.json').write_text(json.dumps({'unit':{'bounds':[-82,28,-80,30]}}))
    cells = sorted([h3.latlng_to_cell(28.5+i*.1,-81,7) for i in range(3)])
    rows = []
    for i,c in enumerate(cells):
        counts = [0]*18
        counts[17 if i==2 else 10] = 10
        rows.append(dict(h3_r7=c,year=2023,class_counts=counts,sampled_pixels=10))
    pq.write_table(pa.Table.from_pylist(rows),land/'unit.parquet')
    epoch = (date(2024,1,1)-date(1970,1,1)).days
    for sensor,chosen in [('Terra',0),('Aqua',1)]:
        writer(dict(cells=np.array(cells,dtype=np.uint64),days=np.array([epoch,epoch+1]),
            clear=np.array([[i==chosen for i in range(3)],[i==0 for i in range(3)]]),
            fire=np.zeros((2,3),bool)),masks/f'unit_{sensor}_sample.parquet',
            {b'granule':b'MOD14A1.A2024001.h10v06.061.test'})
    result = fractions(tmp_path,cells,epoch,epoch+1)
    assert result[0] == 1  # Different sensors jointly observe all land, no double count.
    assert 0 < result[1] < 1
    # No preceding-year classification: future classes cannot establish the denominator.
    assert np.isnan(fractions(tmp_path,cells,epoch-365,epoch-365)).all()
    index = masks/'land_unit.npz'
    np.savez(index,cells=np.array(cells,dtype=np.uint64),first=epoch,fraction=result,revision='obsolete')
    assert np.isnan(load(tmp_path,cells,[epoch])).all()
    np.savez(index,cells=np.array(cells,dtype=np.uint64),first=epoch,fraction=result,revision=revision(tmp_path))
    assert load(tmp_path,cells,[epoch]).tolist() == [1.0]


def test_threshold_selection_never_uses_reserved_year(monkeypatch):
    def project(dates,values,horizon):
        if not np.isfinite(values).any():
            return None
        value = values[np.isfinite(values)][-1]
        return dict(predicted=np.full(horizon,value),seasonal=np.full(horizon,value),
                    lower=np.zeros(horizon),upper=np.full(horizon,10000))
    monkeypatch.setattr(coverage_policy,'project',project)
    dates = np.arange(np.datetime64('2020-01-01'),np.datetime64('2026-01-01'))
    values = np.ones(len(dates))
    first = coverage_policy.assess(dates,values,np.ones(len(dates)))
    values[-365:] = 500
    second = coverage_policy.assess(dates,values,np.ones(len(dates)))
    assert first['selection_candidate'] == second['selection_candidate'] == .95
    assert coverage_policy.assess(dates,values,np.full(len(dates),.69))['selected_threshold'] is None
    assert coverage_policy.assess(dates[:100],values[:100],np.ones(100))['selected_threshold'] is None
