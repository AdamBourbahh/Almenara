def test_observations_aggregates_only_detection_centers(tmp_path, monkeypatch):
    """Raw counts, FRP and all five sensor labels survive without science calls."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    import h3
    from backend.db import duckdb_engine, queries
    from backend.api import routes
    from backend.api.schemas import GeoJSONPolygon
    cell = h3.latlng_to_cell(28.5, -81.3, 7)
    parent = h3.cell_to_parent(cell, 4)
    destination = tmp_path / 'data' / 'processed'
    destination.mkdir(parents=True)
    import datetime
    rows = [dict(acq_date=datetime.date(2026, 1, 2), h3_r4=int(parent,16), h3_r7=int(cell,16),
                 satellite=sensor, frp=power, is_center=True)
            for sensor,power in [('Terra',1.),('Aqua',2.),('SNPP',3.),('N20',4.),('N21',5.)]]
    rows.append({**rows[0], 'is_center':False, 'frp':999.})
    pq.write_table(pa.Table.from_pylist(rows), destination/'staged_firms.parquet')
    monkeypatch.setattr(duckdb_engine,'ROOT',tmp_path)
    monkeypatch.setattr(duckdb_engine,'data_source',lambda:'real')
    monkeypatch.setattr(routes.core_contract,'call',lambda *args: (_ for _ in ()).throw(AssertionError('Science must not run')))
    polygon=GeoJSONPolygon(coordinates=[[[-81.4,28.4],[-81.2,28.4],[-81.2,28.6],[-81.4,28.6],[-81.4,28.4]]])
    result=routes.observations(polygon)
    assert result['data_source']=='real' and result['total_detections']==5
    assert len(result['daily'])==1 and result['daily'][0]['date']=='2026-01-02'
    assert result['daily'][0]['raw_frp_mw']==15
    assert set(result['daily'][0]['sensors'])=={'Terra','Aqua','SNPP','N20','N21'}
    assert result['map_hexagons']==[{'h3_index':cell,'detection_count':5,'raw_frp_mw':15.}]
    assert result['first_observed_date']==result['last_observed_date']=='2026-01-02'
    missing=queries.fetch_observed_detections([],[],2000,2026)
    assert missing=={'daily':[],'map_hexagons':[]}


def test_observations_never_uses_synthetic_cube(tmp_path, monkeypatch):
    from backend.db import duckdb_engine, queries
    import pytest
    directory=tmp_path/'data/processed'
    directory.mkdir(parents=True)
    (directory/'staged_firms.parquet').touch()
    monkeypatch.setattr(duckdb_engine,'ROOT',tmp_path)
    monkeypatch.setattr(duckdb_engine,'data_source',lambda:'synthetic')
    with pytest.raises(ValueError,match='real cube'):
        queries.fetch_observed_detections([],[],2000,2026)


def test_observations_missing_staging_is_service_unavailable(tmp_path, monkeypatch):
    from backend.db import duckdb_engine
    from backend.api import routes
    from backend.api.schemas import GeoJSONPolygon
    from fastapi import HTTPException
    import pytest
    monkeypatch.setattr(duckdb_engine,'ROOT',tmp_path)
    with pytest.raises(HTTPException) as error:
        routes.observations(GeoJSONPolygon(coordinates=[[[-81.4,28.4],[-81.2,28.4],[-81.2,28.6],[-81.4,28.6],[-81.4,28.4]]]))
    assert error.value.status_code==503
