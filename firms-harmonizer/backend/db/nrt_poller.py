"""NASA FIRMS near-real-time (NRT) area API client.

Fetches active-fire CSV for a bounding box through the FIRMS area endpoint and
parses it into plain dictionaries. The module is intentionally offline-safe:
it performs no request at import time and the rest of the API/cube path never
calls it. Use it only for explicit NRT ingestion.

The FIRMS map key is read from ``FIRMS_MAP_KEY`` (``.env`` or the process
environment). The key is part of the request path, so it is never included in
error messages or logs emitted here.
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

import httpx

try:  # python-dotenv is an optional runtime convenience for the CLI.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - the pinned requirements include it
    def load_dotenv(*_args, **_kwargs) -> bool:
        return False

ROOT = Path(__file__).resolve().parents[2]
BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
MAX_DAY_RANGE = 5
DEFAULT_TIMEOUT_SECONDS = 30.0
_SOURCE_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_FLOAT_FIELDS = frozenset({
    "latitude", "longitude", "bright_ti4", "bright_ti5", "brightness",
    "scan", "track", "frp",
})


class NrtPollerError(RuntimeError):
    """Raised for configuration, transport or response errors."""


def _map_key(explicit: str | None = None) -> str:
    """Return a non-empty FIRMS map key without ever logging it."""
    load_dotenv()
    key = (explicit if explicit is not None else os.environ.get("FIRMS_MAP_KEY", "")).strip()
    if not key:
        raise NrtPollerError(
            "FIRMS_MAP_KEY is not set. Add it to the repository .env or export it before polling."
        )
    return key


def _bbox(value: tuple[float, float, float, float] | list[float]) -> str:
    """Validate ``(west, south, east, north)`` and format it for the FIRMS path."""
    try:
        west, south, east, north = (float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise NrtPollerError("The bounding box must be (west, south, east, north) numbers.") from exc
    if not (-180.0 <= west < east <= 180.0):
        raise NrtPollerError("Longitudes must satisfy -180 <= west < east <= 180.")
    if not (-90.0 <= south < north <= 90.0):
        raise NrtPollerError("Latitudes must satisfy -90 <= south < north <= 90.")
    return f"{west:.4f},{south:.4f},{east:.4f},{north:.4f}"


def _source(value: str) -> str:
    source = value.strip()
    if not _SOURCE_RE.fullmatch(source):
        raise NrtPollerError("The FIRMS source may only contain letters, digits, '_' and '-'.")
    return source


def _day_range(value: int) -> int:
    days = int(value)
    if not 1 <= days <= MAX_DAY_RANGE:
        raise NrtPollerError(f"The FIRMS area API accepts a day range of 1..{MAX_DAY_RANGE}.")
    return days


def _date(value: str | date | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        parsed = value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError as exc:
        raise NrtPollerError("The date must be ISO YYYY-MM-DD.") from exc
    if parsed > date.today():
        raise NrtPollerError("The date cannot be in the future.")
    return parsed.isoformat()


def fetch_nrt_csv(
    bbox: tuple[float, float, float, float] | list[float],
    *,
    source: str = "VIIRS_SNPP_NRT",
    days: int = 1,
    start_date: str | date | None = None,
    map_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: httpx.BaseTransport | None = None,
) -> bytes:
    """Return the raw FIRMS CSV for one bbox/source/day-range request.

    ``transport`` is injectable so tests can avoid the network. The request URL
    is built here but never placed in an exception message.
    """
    key = _map_key(map_key)
    area = _bbox(bbox)
    source_id = _source(source)
    day_range = _day_range(days)
    day = _date(start_date)
    url = f"{BASE_URL}/{quote(key, safe='')}/{source_id}/{area}/{day_range}"
    if day is not None:
        url += f"/{day}"
    try:
        with httpx.Client(timeout=timeout, transport=transport, follow_redirects=True) as client:
            response = client.get(url)
    except httpx.HTTPError as exc:
        raise NrtPollerError(f"FIRMS NRT request failed: {type(exc).__name__}.") from None
    if response.status_code != 200:
        raise NrtPollerError(f"FIRMS NRT responded with HTTP {response.status_code}.")
    body = response.content
    if body.lstrip().lower().startswith(b"<"):
        raise NrtPollerError("FIRMS NRT returned an HTML error page instead of CSV.")
    return body


def parse_nrt_csv(raw: bytes) -> list[dict]:
    """Parse a FIRMS CSV payload; known numeric fields become ``float``.

    ``confidence`` is kept as text because VIIRS sends ``n``/``h``/``l`` while
    MODIS sends a percentage. ``acq_time`` stays a four-character UTC string.
    """
    if not raw.strip():
        return []
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return []
    records: list[dict] = []
    for row in reader:
        record: dict = {}
        for name, value in row.items():
            if name is None:
                continue
            cleaned = value.strip() if isinstance(value, str) else value
            if name in _FLOAT_FIELDS and cleaned not in ("", None):
                try:
                    record[name] = float(cleaned)
                    continue
                except (TypeError, ValueError):
                    pass
            record[name] = cleaned
        records.append(record)
    return records


def fetch_nrt(
    bbox: tuple[float, float, float, float] | list[float],
    **kwargs,
) -> list[dict]:
    """Fetch and parse NRT detections for ``bbox`` (see :func:`fetch_nrt_csv`)."""
    return parse_nrt_csv(fetch_nrt_csv(bbox, **kwargs))


def write_nrt_csv(raw: bytes, output: str | Path) -> Path:
    """Write a raw FIRMS CSV payload to ``output`` and return the final path."""
    path = Path(output)
    if path.suffix.lower() != ".csv":
        path = path / "firms_nrt.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Fetch NASA FIRMS NRT active-fire CSV for a bounding box.")
    parser.add_argument("--bbox", nargs=4, type=float, required=True,
                        metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--source", default="VIIRS_SNPP_NRT")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--date", dest="start_date", default=None, help="ISO start date (default: FIRMS latest)")
    parser.add_argument("--output", default=str(ROOT / "data/raw/nrt"))
    args = parser.parse_args()
    try:
        raw = fetch_nrt_csv(args.bbox, source=args.source, days=args.days, start_date=args.start_date)
    except NrtPollerError as exc:
        parser.error(str(exc))
    records = parse_nrt_csv(raw)
    if args.output.endswith(".csv"):
        path = write_nrt_csv(raw, args.output)
    else:
        stamp = args.start_date or date.today().isoformat()
        path = write_nrt_csv(raw, Path(args.output) / f"{args.source}_{stamp}.csv")
    print(f"Wrote {len(records)} detections to {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_cli())
