"""Resumable download of the FIRMS yearly global archives (no API key needed).

Each archive goes to ``data/real/raw/{product}/{year}.zip``. A partial ``.part`` file is resumed with an
HTTP Range request; a finished file is checked against ``Content-Length`` and with ``zipfile.testzip``.
"""

from __future__ import annotations

import argparse
import time
import zipfile
from pathlib import Path

import httpx

from pipeline import config

CHUNK = 1 << 20
RETRIES = 6


def archive_path(product: str, year: int) -> Path:
    return config.RAW / product / f"{year}.zip"


def wanted(products=None, years=None) -> list[tuple[str, int]]:
    out = []
    for product, (first, last) in config.PRODUCTS.items():
        if products and product not in products:
            continue
        out += [(product, y) for y in range(first, last + 1) if not years or y in years]
    return out


def _remote_size(client: httpx.Client, url: str) -> int:
    response = client.head(url, follow_redirects=True)
    response.raise_for_status()
    return int(response.headers["content-length"])


def _verify(path: Path, expected: int) -> None:
    if path.stat().st_size != expected:
        raise IOError(f"{path} has {path.stat().st_size} bytes, expected {expected}")
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise IOError(f"{path}: corrupt member {bad}")


def download_one(client: httpx.Client, product: str, year: int) -> Path:
    path = archive_path(product, year)
    if path.is_file():
        return path
    url = config.ARCHIVE_URL.format(product=product, year=year)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".zip.part")
    expected = _remote_size(client, url)
    for attempt in range(RETRIES):
        try:
            done = part.stat().st_size if part.exists() else 0
            if done < expected:
                headers = {"Range": f"bytes={done}-"} if done else {}
                with client.stream("GET", url, headers=headers, follow_redirects=True) as response:
                    response.raise_for_status()
                    if done and response.status_code != 206:
                        done = 0  # server ignored the range: restart
                    with part.open("ab" if done else "wb") as fh:
                        for chunk in response.iter_bytes(CHUNK):
                            fh.write(chunk)
            _verify(part, expected)
            part.replace(path)
            return path
        except (httpx.HTTPError, IOError) as exc:
            wait = 2 ** attempt
            print(f"  {product} {year}: {type(exc).__name__}: {exc} -> retry in {wait}s", flush=True)
            if part.exists() and part.stat().st_size > expected:
                part.unlink()
            time.sleep(wait)
    raise RuntimeError(f"Could not download {url} after {RETRIES} attempts")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--products", nargs="*", choices=sorted(config.PRODUCTS))
    parser.add_argument("--years", nargs="*", type=int)
    args = parser.parse_args(argv)
    with httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), headers={"User-Agent": "firms-harmonizer-pipeline"}) as client:
        for product, year in wanted(args.products, args.years):
            t0 = time.perf_counter()
            already = archive_path(product, year).is_file()
            path = download_one(client, product, year)
            mb = path.stat().st_size / 1e6
            dt = time.perf_counter() - t0
            print(f"{product:12s} {year}  {mb:8.1f} MB  {'cached' if already else f'{mb / max(dt, 1e-6):6.1f} MB/s'}",
                  flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
