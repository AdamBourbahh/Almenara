#!/usr/bin/env python3
"""Start the FastAPI backend and the Vite dev server together.

The launcher only uses the Python standard library, so it can be started with
any Python 3.8+ interpreter. It finds an interpreter that actually has the
backend dependencies installed (project ``.venv``, ``VIRTUAL_ENV`` or the
interpreter running this script), checks the data cube and the frontend
dependencies, then runs both servers until Ctrl+C.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
IS_WINDOWS = os.name == "nt"


def _venv_python(root: Path) -> Path:
    return root / (".venv/Scripts/python.exe" if IS_WINDOWS else ".venv/bin/python")


def _candidates(explicit: str | None):
    """Yield candidate interpreters, most specific first."""
    seen: set[str] = set()
    virtual_env = os.environ.get("VIRTUAL_ENV")
    values = [
        explicit,
        os.environ.get("FIRMS_PYTHON"),
        str(_venv_python(ROOT)),
        str(Path(virtual_env) / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")) if virtual_env else None,
        sys.executable,
        str(ROOT / "venv" / ("Scripts/python.exe" if IS_WINDOWS else "bin/python")),
        shutil.which("python3"),
        shutil.which("python"),
    ]
    for value in values:
        if not value:
            continue
        key = os.path.normcase(os.path.abspath(value))
        if key in seen:
            continue
        seen.add(key)
        yield value


def find_backend_python(explicit: str | None) -> str | None:
    for candidate in _candidates(explicit):
        if not Path(candidate).exists() and not shutil.which(candidate):
            continue
        try:
            probe = subprocess.run(
                [candidate, "-c", "import uvicorn, fastapi, duckdb"],
                capture_output=True,
                timeout=25,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


def port_available(host: str, port: int) -> bool:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def stop_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    try:
        if IS_WINDOWS:
            process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=6)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        if IS_WINDOWS:
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def main() -> int:
    # A background shell may inherit SIGINT as ignored. Install handlers so a
    # Ctrl+C or a supervisor's SIGTERM always reaches the cleanup block.
    def stop_on_signal(_signum, _frame):
        raise KeyboardInterrupt
    for handled in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(handled, stop_on_signal)
        except (ValueError, OSError):
            pass

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1", help="API bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="API port (default: 8000)")
    parser.add_argument("--web-port", type=int, default=5173, help="Vite port (default: 5173)")
    parser.add_argument("--python", default=argparse.SUPPRESS, help="Python interpreter with backend dependencies")
    parser.add_argument("--no-reload", action="store_true", help="Disable uvicorn's file reloader")
    args = parser.parse_args()
    explicit = getattr(args, "python", None)

    python = find_backend_python(explicit)
    if python is None:
        print("Backend dependencies are missing (uvicorn, fastapi, duckdb).", file=sys.stderr)
        print("Create the environment and install the locked dependencies:", file=sys.stderr)
        print("  python3 -m venv .venv", file=sys.stderr)
        print("  .venv/bin/pip install -r requirements.lock", file=sys.stderr)
        print("Then run 'make dev' again, or pass --python /path/to/venv/bin/python.", file=sys.stderr)
        return 1

    if not FRONTEND.is_dir() or not (FRONTEND / "package.json").is_file():
        print(f"Frontend not found at {FRONTEND}.", file=sys.stderr)
        return 1
    if not (FRONTEND / "node_modules").is_dir():
        print("Frontend dependencies are missing. Run 'cd frontend && npm ci' first.", file=sys.stderr)
        return 1

    cube = ROOT / "data/processed/fire_cube.parquet"
    synthetic = os.environ.get("USE_SYNTHETIC_CUBE") == "1"
    if not cube.is_file() and not synthetic:
        print(f"No real cube at {cube}.", file=sys.stderr)
        print("Build it with 'python scripts/run_pipeline.py etl' or opt into the fixture", file=sys.stderr)
        print("with USE_SYNTHETIC_CUBE=1.", file=sys.stderr)
        return 1

    if not port_available(args.host, args.port):
        print(f"Port {args.port} is already in use on {args.host}.", file=sys.stderr)
        print(f"Stop the running API or use '--port {args.port + 1}'.", file=sys.stderr)
        return 1
    if not port_available("127.0.0.1", args.web_port):
        print(f"Port {args.web_port} is already in use (Vite).", file=sys.stderr)
        print(f"Stop the running dev server or use '--web-port {args.web_port + 1}'.", file=sys.stderr)
        return 1

    backend_cmd = [
        python, "-m", "uvicorn", "backend.api.main:app",
        "--host", args.host, "--port", str(args.port),
    ]
    if not args.no_reload:
        backend_cmd.append("--reload")
    npm = "npm.cmd" if IS_WINDOWS else "npm"
    web_cmd = [npm, "run", "dev", "--", "--port", str(args.web_port)]
    env = os.environ.copy()

    print(f"Using backend Python: {python}")
    print(f"API:      http://{args.host}:{args.port}")
    print(f"Frontend: http://localhost:{args.web_port}")
    print("Press Ctrl+C to stop both.\n", flush=True)

    backend: subprocess.Popen | None = None
    web: subprocess.Popen | None = None
    try:
        backend = subprocess.Popen(backend_cmd, cwd=ROOT, env=env, start_new_session=not IS_WINDOWS)
        time.sleep(1.5)
        if backend.poll() is not None:
            print("The API exited during startup. See the messages above.", file=sys.stderr)
            return backend.returncode or 1
        web = subprocess.Popen(web_cmd, cwd=FRONTEND, env=env, start_new_session=not IS_WINDOWS)
        while True:
            backend_code = backend.poll()
            web_code = web.poll()
            if backend_code is not None:
                print(f"The API exited with code {backend_code}.", file=sys.stderr)
                return backend_code or 1
            if web_code is not None:
                print(f"The frontend exited with code {web_code}.", file=sys.stderr)
                return web_code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping the API and the frontend…", flush=True)
        return 0
    finally:
        stop_process(web)
        stop_process(backend)


if __name__ == "__main__":
    raise SystemExit(main())
