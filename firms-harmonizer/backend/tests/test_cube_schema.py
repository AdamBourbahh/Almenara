"""Schema, physical scenario and cross-language contract regression gates."""

import ast
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter

import numpy as np
import orjson
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from backend.api.schemas import AnalyzeRequest, AnalyzeResponse, ChaosMonkeyRequest, GeoJSONPolygon

spec = importlib.util.spec_from_file_location("bootstrap",ROOT/"scripts/00_bootstrap_synthetic_cube.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

EXPECTED = [
    ("h3_r4",pa.uint64()),("h3_r7",pa.uint64()),("epoch_day",pa.uint16()),
    ("year",pa.uint16()),("doy",pa.uint16()),("igbp_biome",pa.uint8()),
    ("sensor_obs_mask",pa.uint8()),("gap_status_mask",pa.uint8()),
    ("cloud_cover_pct",pa.float32()),("raw_modis_cnt",pa.uint16()),
    ("raw_viirs_cnt",pa.uint16()),("raw_frp_mw",pa.float32()),
    ("obs_terra_fre",pa.float32()),("obs_aqua_fre",pa.float32()),
    ("obs_viirs_fre",pa.float32()),("neighbor_fre_lag1",pa.float32()),
    ("industrial_prob",pa.float32()),("burned_area_ha_mcd64",pa.float32()),
]


@pytest.fixture(scope="module")
def cube():
    path = ROOT/"data/processed/fire_cube.parquet"
    assert path.is_file(), "Run python3 scripts/00_bootstrap_synthetic_cube.py first."
    return pq.read_table(path)


def test_exact_schema_and_compression(cube):
    assert [(f.name,f.type) for f in cube.schema] == EXPECTED
    assert [f.name for f in cube.schema if f.nullable] == ["obs_terra_fre","obs_aqua_fre","obs_viirs_fre"]
    parquet = pq.ParquetFile(ROOT/"data/processed/fire_cube.parquet")
    for i in range(parquet.metadata.num_row_groups):
        for j in range(18):
            assert parquet.metadata.row_group(i).column(j).compression == "ZSTD"
    assert b"SYNTHETIC" in cube.schema.metadata[b"source"]


def test_sorted_and_unique(cube):
    r4,day,r7 = [cube[n].to_numpy() for n in ["h3_r4","epoch_day","h3_r7"]]
    order = np.lexsort((r7,day,r4))
    assert np.array_equal(order,np.arange(len(day)))
    assert len(set(zip(r7.tolist(),day.tolist()))) == len(day)


def test_four_regions_and_daily_coverage(cube):
    actual = set(cube["h3_r7"].to_pylist())
    expected = set()
    days = len(np.arange(np.datetime64("2001-01-01"),np.datetime64("2027-01-01")))
    for lat,lon,_,_ in bootstrap.REGIONS.values():
        cells = bootstrap.region_cells(lat,lon)
        expected.update(int(h,16) for h in cells)
    assert actual == expected
    assert len(cube) == days*len(expected)
    for h,parent in zip(cube["h3_r7"].to_pylist()[::1000],cube["h3_r4"].to_pylist()[::1000]):
        assert int(bootstrap.parent_r4(f"{h:x}"),16)==parent
    for h in actual:
        selected = cube.filter(pa.compute.equal(cube["h3_r7"],h))
        assert len(selected)==days
        assert selected["epoch_day"][0].as_py()==366
        assert selected["year"][-1].as_py()==2026


def test_calendar_keys(cube):
    dates = np.datetime64("2000-01-01")+cube["epoch_day"].to_numpy().astype("timedelta64[D]")
    assert np.array_equal(dates.astype("datetime64[Y]").astype(int)+1970,cube["year"].to_numpy())
    assert np.array_equal((dates-dates.astype("datetime64[Y]")).astype(int)+1,cube["doy"].to_numpy())


def test_outages_and_sensor_masks(cube):
    days = cube["epoch_day"].to_numpy()
    def between(start,end):
        lo=int((np.datetime64(start)-np.datetime64("2000-01-01")).astype(int))
        hi=int((np.datetime64(end)-np.datetime64("2000-01-01")).astype(int))
        return (days>=lo)&(days<=hi)
    aqua = between("2022-07-31","2022-08-16")
    black = between("2022-08-22","2022-08-26")
    flags = cube["gap_status_mask"].to_numpy()
    obs=np.column_stack([cube[n].to_numpy() for n in ["obs_terra_fre","obs_aqua_fre","obs_viirs_fre"]])
    assert aqua.sum()==17*28 and black.sum()==5*28
    assert np.all(np.isnan(obs[aqua,1])) and np.all(np.isfinite(obs[aqua][:,[0,2]]))
    assert np.all(flags[aqua]==1) and np.all(flags[black]==8)
    assert np.all(np.isnan(obs[black]))
    assert np.all(cube["cloud_cover_pct"].to_numpy()[black]==100)
    assert np.array_equal(np.sum(np.isfinite(obs)*[1,2,4],axis=1),cube["sensor_obs_mask"].to_numpy())
    assert np.all(np.isnan(obs[cube["year"].to_numpy()<2012,2]))
    assert np.all(flags[~(aqua|black)]==0)


def test_instrumental_jump_and_physical_stability(cube):
    years=cube["year"].to_numpy()
    modis=cube["raw_modis_cnt"].to_numpy()
    viirs=cube["raw_viirs_cnt"].to_numpy()
    assert np.all(viirs[years<2012]==0)
    assert np.array_equal(viirs[years>=2012],np.rint(modis[years>=2012]*5.2).astype(np.uint16))
    terra=cube["obs_terra_fre"].to_numpy()
    assert .95 < np.nanmean(terra[years<2012])/np.nanmean(terra[years>=2012]) < 1.05
    for sensor in ["obs_aqua_fre","obs_viirs_fre"]:
        x=cube[sensor].to_numpy()
        available=np.isfinite(x)&np.isfinite(terra)
        assert .98 < np.mean(x[available])/np.mean(terra[available]) < 1.02


def test_industrial_and_climate_scenarios(cube):
    cells=bootstrap.region_cells(5,6)
    industrial=pa.compute.is_in(cube["h3_r7"],value_set=pa.array([int(h,16) for h in cells],type=pa.uint64()))
    selected=cube.filter(industrial)
    assert np.allclose(selected["industrial_prob"].to_numpy(),.92)
    natural=cube.filter(pa.compute.invert(industrial))
    assert np.all(natural["industrial_prob"].to_numpy()<.75)
    for name,(lat,lon,_,_) in bootstrap.REGIONS.items():
        one=cube.filter(pa.compute.equal(cube["h3_r7"],int(bootstrap.region_cells(lat,lon)[0],16)))
        y=one["year"].to_numpy()
        energy=one["obs_terra_fre"].to_numpy()
        if name=="niger_delta_flaring":
            assert np.nanstd(energy)/np.nanmean(energy)<.05
        else:
            days=one["doy"].to_numpy()
            peaks=[]
            for year in range(2001,2027):
                mask=(y==year)&np.isfinite(energy)
                z=np.sum(energy[mask]*np.exp(2j*np.pi*(days[mask]-1)/365.25))
                peaks.append(1+(np.angle(z)%(2*np.pi))*365.25/(2*np.pi))
            assert .65<np.polyfit(np.arange(26),peaks,1)[0]<.85


def test_mock_matches_contract_and_typescript(cube):
    payload=orjson.loads((ROOT/"data/mock/mock_analyze_response.json").read_bytes())
    response=AnalyzeResponse.model_validate(payload)
    assert len(response.calendar_series)==9496
    assert len(response.forecast_series)==14
    assert len(response.phenology_by_year)==26
    assert response.forecast_series[0].date=="2027-01-01"
    assert "Synthetic" in response.audit_metrics.executive_verdict_en
    assert all(len(h.h3_index)==15 for h in response.map_hexagons)
    source=ast.parse((ROOT/"backend/api/schemas.py").read_text())
    ts=(ROOT/"frontend/src/api/types.ts").read_text()
    for node in source.body:
        if not isinstance(node,ast.ClassDef) or node.name=="ContractModel":
            continue
        body=re.search(r"export interface "+node.name+r" \{(.*?)\n\}",ts,re.S).group(1)
        assert set(re.findall(r"^  (\w+)\??:",body,re.M)) == {n.target.id for n in node.body if isinstance(n,ast.AnnAssign)}
    assert set(re.findall(r"^  (\w+): \{",ts,re.M)) == set(bootstrap.REGIONS)


def test_request_validation():
    aoi=GeoJSONPolygon(coordinates=[[[-6,38],[-4,38],[-4,40],[-6,38]]])
    assert AnalyzeRequest(aoi=aoi).forecast_days==14
    assert ChaosMonkeyRequest(aoi=aoi).drop_fraction==.25
    for arguments in [dict(start_year=2025,end_year=2020),dict(forecast_days=15),dict(confidence_level="invalid")]:
        with pytest.raises(ValidationError):
            AnalyzeRequest(aoi=aoi,**arguments)
    with pytest.raises(ValidationError):
        GeoJSONPolygon(coordinates=[[[0,0],[1,0],[1,1],[float("nan"),0]]])


def test_generator_repeatability_performance_and_alternate_path(tmp_path,cube):
    start=perf_counter()
    path=bootstrap.generate_bootstrap_cube(tmp_path/"repeat.parquet")
    assert perf_counter()-start<4.0
    assert pq.read_table(path).equals(cube)
    # A foreign working directory must not alter the default output location.
    result=subprocess.run([sys.executable,str(ROOT/"scripts/00_bootstrap_synthetic_cube.py")],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_v3_compatibility_adapter(monkeypatch):
    cells=bootstrap.region_cells(-16,-48)
    expected_parent=bootstrap.parent_r4(cells[0])
    class V3:
        @staticmethod
        def geo_to_h3(lat,lon,res):
            assert (lat,lon,res)==(-16,-48,7)
            return cells[0]
        @staticmethod
        def k_ring(cell,k):
            assert k==1
            return cells
        @staticmethod
        def h3_to_parent(cell,res):
            assert res==4
            return expected_parent
    monkeypatch.setattr(bootstrap,"h3",V3)
    assert bootstrap.region_cells(-16,-48)==cells
    assert bootstrap.parent_r4(cells[0])==expected_parent
