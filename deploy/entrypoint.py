"""Container entrypoint: fetch the runtime data, then serve the API and the built frontend.

Runtime data (the cube, accepted detections and ignored lookup tables) is not in git. When
DATA_REPO names a Hugging Face dataset, it is downloaded into ``data/`` at start-up and the
original modification times are restored from its manifest, because cache keys and coverage
revision stamps use them. Without a real cube the API refuses to start, exactly as it does
locally: synthetic data is served only with an explicit USE_SYNTHETIC_CUBE=1.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

APP_ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parent))
DATA_DIR = APP_ROOT / "data"
CUBE = DATA_DIR / "processed" / "fire_cube.parquet"
MANIFEST = "manifest.json"
DATA_PATTERNS = ["processed/**", "lookup/**", "cache/**", MANIFEST]


def log(message: str) -> None:
    print(f"[entrypoint] {message}", flush=True)


def fetch_runtime_data(repo: str, attempts: int = 4) -> None:
    from huggingface_hub import snapshot_download

    for attempt in range(1, attempts + 1):
        try:
            snapshot_download(repo_id=repo, repo_type="dataset", local_dir=DATA_DIR,
                              revision=os.environ.get("DATA_REVISION") or None,
                              token=os.environ.get("HF_TOKEN") or None, allow_patterns=DATA_PATTERNS)
            return
        except Exception as error:  # network or hub outage: retry, then fail with the cause
            if attempt == attempts:
                raise SystemExit(f"[entrypoint] Could not download runtime data from {repo}: {type(error).__name__}: {error}")
            log(f"Download attempt {attempt} failed ({type(error).__name__}); retrying.")
            time.sleep(5 * attempt)


def restore_modification_times() -> int:
    manifest = DATA_DIR / MANIFEST
    if not manifest.is_file():
        return 0
    restored = 0
    for relative, mtime_ns in json.loads(manifest.read_text(encoding="utf-8"))["files"].items():
        path = DATA_DIR / relative
        if path.is_file():
            os.utime(path, ns=(mtime_ns, mtime_ns))
            restored += 1
    return restored


def main() -> None:
    repo = os.environ.get("DATA_REPO", "").strip()
    if repo and not CUBE.is_file():
        log(f"Downloading runtime data from dataset {repo}.")
        started = time.monotonic()
        fetch_runtime_data(repo)
        log(f"Runtime data ready in {time.monotonic() - started:.1f} s; restored {restore_modification_times()} timestamps.")
    elif CUBE.is_file():
        restore_modification_times()
    if os.environ.get("USE_SYNTHETIC_CUBE") != "1" and not CUBE.is_file():
        raise SystemExit(f"[entrypoint] Real cube missing at {CUBE}. Set DATA_REPO to the published data "
                         "dataset, mount data/processed, or set USE_SYNTHETIC_CUBE=1 for the labelled demo cube.")
    port = os.environ.get("PORT", "7860")
    os.chdir(APP_ROOT)
    log(f"Starting the API and frontend on port {port}.")
    # Proxy headers give each visitor its own rate-limit bucket behind the platform's proxy.
    os.execvp(sys.executable, [sys.executable, "-m", "uvicorn", "backend.api.main:app", "--host", "0.0.0.0",
                               "--port", port, "--proxy-headers", "--forwarded-allow-ips", "*",
                               "--log-level", os.environ.get("LOG_LEVEL", "info")])


if __name__ == "__main__":
    main()
