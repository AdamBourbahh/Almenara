"""Publish FIRMS Harmonizer to Hugging Face: runtime data to a dataset, the app to a Docker Space.

    python deploy/publish.py data  --repo <user>/firms-harmonizer-data
    python deploy/publish.py space --repo <user>/firms-harmonizer --data-repo <user>/firms-harmonizer-data
    python deploy/publish.py status --repo <user>/firms-harmonizer

The token comes from HF_TOKEN or a cached `hf auth login`; it is never printed. The Space
receives only git-tracked source files, so local secrets, raw downloads and caches never
leave the machine. Optional model and FIRMS keys become Space secrets only with
--secrets-from-env, read from this process's environment.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "firms-harmonizer"
DATA = APP / "data"
SPACE_CARD = REPO_ROOT / "deploy" / "space_card.md"
DATASET_CARD = REPO_ROOT / "deploy" / "dataset_card.md"

# Runtime artifacts the API reads that are excluded from git (paths relative to data/).
RUNTIME_DATA = [
    "processed/fire_cube.parquet", "processed/fire_cube_low.parquet", "processed/fire_cube_high.parquet",
    "processed/staged_firms.parquet", "lookup/cell_day_ancillary.parquet", "lookup/diurnal_ratios.parquet",
    "lookup/igbp_cells.parquet", "lookup/sensor_outages.parquet",
]
RUNTIME_DIRECTORIES = ["processed/observation_coverage", "cache/land_cover"]
REQUIRED_DATA = "processed/fire_cube.parquet"

# Git-tracked source files the Space needs to build the Dockerfile.
SPACE_FILES = ["Dockerfile", ".dockerignore", "deploy/entrypoint.py", "deploy/requirements.txt"]
SPACE_PREFIXES = ["firms-harmonizer/backend/", "firms-harmonizer/frontend/", "firms-harmonizer/data/",
                  "firms-harmonizer/scripts/"]
SPACE_EXCLUDED = ["firms-harmonizer/backend/tests/", "firms-harmonizer/frontend/tests/",
                  "firms-harmonizer/data/raw/", "firms-harmonizer/data/processed/"]
OPTIONAL_SECRETS = ["GEMINI_API_KEY", "GROQ_API_KEY", "TAVILY_API_KEY", "FIRMS_MAP_KEY"]
KEPT_REMOTE = {".gitattributes", "README.md"}


def api() -> HfApi:
    client = HfApi(token=os.environ.get("HF_TOKEN") or None)
    try:
        user = client.whoami()["name"]
    except Exception as error:
        raise SystemExit("No Hugging Face credentials: set HF_TOKEN to a write token or run `hf auth login`. "
                         f"({type(error).__name__})")
    print(f"Authenticated as {user}.")
    return client


def sync_operations(client: HfApi, repo: str, repo_type: str, files: dict[str, Path | bytes]) -> list:
    """Add every local file and delete remote files that are no longer published."""
    remote = set(client.list_repo_files(repo, repo_type=repo_type))
    operations: list = [CommitOperationAdd(path, source if isinstance(source, bytes) else str(source))
                        for path, source in sorted(files.items())]
    operations += [CommitOperationDelete(path) for path in sorted(remote - set(files) - KEPT_REMOTE)]
    return operations


def runtime_files() -> dict[str, Path]:
    files = {relative: DATA / relative for relative in RUNTIME_DATA if (DATA / relative).is_file()}
    for directory in RUNTIME_DIRECTORIES:
        for path in sorted((DATA / directory).rglob("*")):
            if path.is_file() and ".tmp." not in path.name:
                files[path.relative_to(DATA).as_posix()] = path
    if REQUIRED_DATA not in files:
        raise SystemExit(f"Missing {DATA / REQUIRED_DATA}. Build the real cube first (python scripts/run_pipeline.py etl).")
    return files


def publish_data(args) -> None:
    client = api()
    files = runtime_files()
    manifest = {"files": {relative: path.stat().st_mtime_ns for relative, path in files.items()}}
    payload: dict[str, Path | bytes] = dict(files)
    payload["manifest.json"] = json.dumps(manifest, indent=1, sort_keys=True).encode()
    payload["README.md"] = DATASET_CARD.read_bytes()
    size = sum(path.stat().st_size for path in files.values()) / 1e6
    print(f"Publishing {len(files)} runtime files ({size:,.1f} MB) to dataset {args.repo}.")
    client.create_repo(args.repo, repo_type="dataset", private=args.private, exist_ok=True)
    operations = sync_operations(client, args.repo, "dataset", payload)
    client.create_commit(args.repo, operations, repo_type="dataset",
                         commit_message=f"Publish runtime data ({len(files)} files)")
    print(f"Done: https://huggingface.co/datasets/{args.repo}")


def tracked_space_files() -> dict[str, Path | bytes]:
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO_ROOT, check=True,
                             capture_output=True).stdout.decode("utf-8").split("\0")
    files: dict[str, Path | bytes] = {}
    for path in filter(None, tracked):
        if path in SPACE_FILES or (path.startswith(tuple(SPACE_PREFIXES)) and not path.startswith(tuple(SPACE_EXCLUDED))):
            if (REPO_ROOT / path).is_file():
                files[path] = REPO_ROOT / path
    missing = [path for path in SPACE_FILES if path not in files]
    if missing:
        raise SystemExit(f"Commit these deployment files before publishing: {', '.join(missing)}")
    files["README.md"] = SPACE_CARD.read_bytes()
    return files


def configure_space(client: HfApi, args) -> None:
    secrets = {name: os.environ[name] for name in OPTIONAL_SECRETS if args.secrets_from_env and os.environ.get(name)}
    for name, value in secrets.items():
        client.add_space_secret(args.repo, name, value)
    current = client.get_space_variables(args.repo)
    has_model = bool(secrets.get("GEMINI_API_KEY") or secrets.get("GROQ_API_KEY")
                     or "COPILOT_PROVIDER" in current)
    variables = {"DATA_REPO": args.data_repo, "NRT_POLLING": "0", "USE_SYNTHETIC_CUBE": "0"}
    if args.secrets_from_env:
        variables["COPILOT_OFFLINE"] = "0" if has_model else "1"
        if secrets.get("GEMINI_API_KEY"):
            variables["COPILOT_PROVIDER"] = "gemini"
        elif secrets.get("GROQ_API_KEY"):
            variables["COPILOT_PROVIDER"] = "groq"
    elif "COPILOT_OFFLINE" not in current:
        variables["COPILOT_OFFLINE"] = "1"
    for name, value in variables.items():
        client.add_space_variable(args.repo, name, value)
    print(f"Space variables: {', '.join(f'{k}={v}' for k, v in sorted(variables.items()))}; "
          f"secrets set: {', '.join(sorted(secrets)) or 'none'}.")


def publish_space(args) -> None:
    client = api()
    files = tracked_space_files()
    print(f"Publishing {len(files)} source files to Space {args.repo}.")
    client.create_repo(args.repo, repo_type="space", space_sdk="docker", private=args.private, exist_ok=True)
    configure_space(client, args)
    revision = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    client.create_commit(args.repo, sync_operations(client, args.repo, "space", files), repo_type="space",
                         commit_message=f"Deploy {revision}")
    print(f"Pushed {revision}. The Space rebuilds automatically: https://huggingface.co/spaces/{args.repo}")
    if args.wait:
        wait_until_running(client, args.repo, args.timeout)


def wait_until_running(client: HfApi, repo: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    stage = None
    while time.monotonic() < deadline:
        runtime = client.get_space_runtime(repo)
        if runtime.stage != stage:
            stage = runtime.stage
            print(f"Space stage: {stage}")
        if stage in ("BUILD_ERROR", "CONFIG_ERROR", "RUNTIME_ERROR", "NO_APP_FILE"):
            raise SystemExit(f"Deployment failed ({stage}). Open https://huggingface.co/spaces/{repo}?logs=container")
        if stage == "RUNNING":
            break
        time.sleep(15)
    else:
        raise SystemExit("Timed out waiting for the Space; it may still be building.")
    host = client.space_info(repo).host or f"https://{repo.replace('/', '-').replace('_', '-').replace('.', '-').lower()}.hf.space"
    for attempt in range(20):
        try:
            with urllib.request.urlopen(f"{host}/api/health", timeout=20) as response:
                health = json.loads(response.read())
            print(f"Live: {host} | health={health.get('status')} data_source={health.get('data_source')} rows={health.get('row_count')}")
            return
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(10)
    raise SystemExit(f"The Space is running but {host}/api/health did not answer.")


def status(args) -> None:
    client = api()
    runtime = client.get_space_runtime(args.repo)
    print(f"Stage: {runtime.stage} | hardware: {runtime.hardware} | host: {client.space_info(args.repo).host}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    data = commands.add_parser("data", help="Upload runtime data to a Hugging Face dataset.")
    data.add_argument("--repo", required=True)
    data.add_argument("--private", action="store_true", help="Private dataset; the Space then needs an HF_TOKEN secret.")
    data.set_defaults(func=publish_data)
    space = commands.add_parser("space", help="Create or update the Docker Space.")
    space.add_argument("--repo", required=True)
    space.add_argument("--data-repo", required=True)
    space.add_argument("--private", action="store_true")
    space.add_argument("--secrets-from-env", action="store_true",
                       help=f"Copy {', '.join(OPTIONAL_SECRETS)} from the environment into Space secrets.")
    space.add_argument("--wait", action="store_true", help="Wait for the build and check /api/health.")
    space.add_argument("--timeout", type=float, default=1800)
    space.set_defaults(func=publish_space)
    check = commands.add_parser("status", help="Show the Space stage.")
    check.add_argument("--repo", required=True)
    check.set_defaults(func=status)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
