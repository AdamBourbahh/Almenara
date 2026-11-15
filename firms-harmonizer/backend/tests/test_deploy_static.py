"""Single-origin deployment: the built frontend is served next to the API without shadowing it."""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_frontend(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>FIRMS Harmonizer</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIST", str(dist))
    from backend.api import main
    reloaded = importlib.reload(main)
    yield reloaded.app
    monkeypatch.delenv("FRONTEND_DIST")
    importlib.reload(main)


def test_frontend_and_api_share_one_origin(app_with_frontend):
    with TestClient(app_with_frontend) as client:
        page = client.get("/")
        assert page.status_code == 200 and "FIRMS Harmonizer" in page.text
        assert page.headers["content-type"].startswith("text/html")
        assert client.get("/assets/app.js").status_code == 200
        health = client.get("/api/health")
        assert health.status_code == 200 and health.json()["status"] == "ok"
        assert client.get("/api/does-not-exist").status_code == 404


def test_without_a_build_only_the_api_is_served(monkeypatch):
    monkeypatch.delenv("FRONTEND_DIST", raising=False)
    from backend.api import main
    app = importlib.reload(main).app
    with TestClient(app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/health").status_code == 200


def load_deploy_module(name):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / "deploy" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"deploy_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_space_upload_contains_only_tracked_source_and_no_secrets_or_data():
    pytest.importorskip("huggingface_hub")
    publish = load_deploy_module("publish")
    files = publish.tracked_space_files()
    assert {"Dockerfile", ".dockerignore", "deploy/entrypoint.py", "README.md"} <= set(files)
    assert "firms-harmonizer/backend/api/main.py" in files and "firms-harmonizer/data/regions.json" in files
    assert files["README.md"].startswith(b"---\n") and b"sdk: docker" in files["README.md"]
    forbidden = ("/data/raw/", "/data/processed/", "/backend/tests/", "node_modules", ".venv")
    assert not [path for path in files if any(part in path for part in forbidden)]
    names = [path.rsplit("/", 1)[-1] for path in files]
    assert not [name for name in names if name == ".env" or (name.startswith(".env.") and name != ".env.example")]
    assert not [path for path in files if path.endswith(".parquet") and "modis_swath_gaps" not in path]


def test_entrypoint_restores_published_modification_times(tmp_path, monkeypatch):
    import json, os
    entrypoint = load_deploy_module("entrypoint")
    monkeypatch.setattr(entrypoint, "DATA_DIR", tmp_path)
    (tmp_path / "processed").mkdir()
    cube = tmp_path / "processed" / "fire_cube.parquet"
    cube.write_bytes(b"cube")
    stamp = 1_700_000_000_123_456_700  # a multiple of 100 ns, exact on NTFS as well as ext4
    (tmp_path / "manifest.json").write_text(json.dumps({"files": {"processed/fire_cube.parquet": stamp,
                                                                  "processed/absent.parquet": 1}}))
    assert entrypoint.restore_modification_times() == 1
    assert os.stat(cube).st_mtime_ns == stamp


def test_entrypoint_refuses_to_start_without_a_real_cube(tmp_path, monkeypatch):
    entrypoint = load_deploy_module("entrypoint")
    monkeypatch.setattr(entrypoint, "CUBE", tmp_path / "processed" / "fire_cube.parquet")
    monkeypatch.delenv("DATA_REPO", raising=False)
    monkeypatch.setenv("USE_SYNTHETIC_CUBE", "0")
    with pytest.raises(SystemExit, match="Real cube missing"):
        entrypoint.main()


def test_missing_build_directory_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("FRONTEND_DIST", str(tmp_path / "absent"))
    from backend.api import main
    app = importlib.reload(main).app
    assert not any(getattr(route, "name", "") == "frontend" for route in app.routes)
    monkeypatch.delenv("FRONTEND_DIST")
    importlib.reload(main)
