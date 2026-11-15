"""Build the Marp pitch deck (EN + ES) from the real FIRMS cube.

Usage (from this folder):  python build.py
Requires: Python with duckdb, Node.js (npx), and Microsoft Edge or Chrome for PDF/PPTX.
The detection chart is regenerated from firms-harmonizer/data/processed/fire_cube.parquet,
so the bars always match the data the live demo serves.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
CUBE = HERE.parents[2] / "firms-harmonizer" / "data" / "processed" / "fire_cube.parquet"
MARP = "@marp-team/marp-cli@4.1.2"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def annual_detections() -> list[tuple[int, int, int]]:
    query = (
        "SELECT year, SUM(raw_modis_cnt)::BIGINT, SUM(raw_viirs_cnt)::BIGINT "
        f"FROM read_parquet('{CUBE.as_posix()}') GROUP BY 1 ORDER BY 1"
    )
    return duckdb.connect().sql(query).fetchall()


def fmt(value: int, lang: str) -> str:
    text = f"{value:,}"
    return text.replace(",", ".") if lang == "es" else text


def chart_svg(rows: list[tuple[int, int, int]], lang: str) -> str:
    width, height, left, base, top = 1000, 330, 60, 290, 20
    peak = max(m + v for _, m, v in rows)
    ceiling = ((peak // 50000) + 1) * 50000
    bar_w = (width - left - 10) / len(rows)
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height + 20}" role="img" aria-label="'
             + ("Raw satellite detections per year" if lang == "en" else "Detecciones satelitales crudas por año")
             + '">']
    for tick in range(0, ceiling, 50000):
        y = base - (base - top) * tick / ceiling
        parts.append(f'<line x1="{left}" x2="{width - 10}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{left - 8}" y="{y + 5:.1f}" class="ax" text-anchor="end">{tick // 1000}k</text>')
    cut_x = None
    for i, (year, modis, viirs) in enumerate(rows):
        x = left + i * bar_w + 3
        h_m = (base - top) * modis / ceiling
        h_v = (base - top) * viirs / ceiling
        partial = year in (rows[0][0], rows[-1][0])
        note = ""
        if partial:
            note = " (partial year)" if lang == "en" else " (año parcial)"
        tip = f"{year}{note}: MODIS {fmt(modis, lang)} · VIIRS {fmt(viirs, lang)} · total {fmt(modis + viirs, lang)}"
        klass = "bar partial" if partial else "bar"
        parts.append(f'<g class="{klass}"><title>{tip}</title>'
                     f'<rect x="{x:.1f}" y="{base - h_m:.1f}" width="{bar_w - 6:.1f}" height="{h_m:.1f}" class="modis"/>'
                     f'<rect x="{x:.1f}" y="{base - h_m - h_v:.1f}" width="{bar_w - 6:.1f}" height="{h_v:.1f}" class="viirs"/></g>')
        if year % 4 == 0 or year == rows[-1][0]:
            parts.append(f'<text x="{x + (bar_w - 6) / 2:.1f}" y="{base + 20}" class="ax" text-anchor="middle">{year}</text>')
        if year == 2012:
            cut_x = x - 3
    if cut_x is not None:
        label = "VIIRS joins · Jan 2012" if lang == "en" else "Entra VIIRS · ene 2012"
        parts.append(f'<line x1="{cut_x:.1f}" x2="{cut_x:.1f}" y1="{top}" y2="{base}" class="cut"/>'
                     f'<text x="{cut_x - 8:.1f}" y="{top + 16}" class="cutlbl" text-anchor="end">{label}</text>')
    parts.append("</svg>")
    return "".join(parts)


def jump_stats(rows: list[tuple[int, int, int]], lang: str) -> dict[str, str]:
    by_year = {year: (m, v) for year, m, v in rows}
    total_2011 = sum(by_year[2011])
    total_2012 = sum(by_year[2012])
    modis_2012, viirs_2012 = by_year[2012]
    return {
        "{{T2011}}": fmt(total_2011, lang),
        "{{T2012}}": fmt(total_2012, lang),
        "{{JUMP}}": f"+{round(100 * (total_2012 - total_2011) / total_2011)}",
        "{{RATIO}}": f"{viirs_2012 / modis_2012:.1f}".replace(".", "," if lang == "es" else "."),
    }


def browser_path() -> str | None:
    if os.environ.get("CHROME_PATH"):
        return os.environ["CHROME_PATH"]
    return next((path for path in BROWSERS if Path(path).exists()), None)


def main() -> None:
    rows = annual_detections()
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        sys.exit("npx not found: install Node.js")
    env = dict(os.environ)
    browser = browser_path()
    if browser:
        env["CHROME_PATH"] = browser
    for lang in ("en", "es"):
        source = (HERE / f"slides.{lang}.tpl.md").read_text(encoding="utf-8")
        source = source.replace("{{CHART}}", chart_svg(rows, lang))
        for key, value in jump_stats(rows, lang).items():
            source = source.replace(key, value)
        deck = HERE / f"almenara-pitch.{lang}.md"
        deck.write_text(source, encoding="utf-8")
        outputs = ["html"] + (["pdf", "pptx"] if browser else [])
        for ext in outputs:
            subprocess.run(
                [npx, "--yes", MARP, str(deck), "--html", "--allow-local-files", "-o", str(HERE / f"almenara-pitch.{lang}.{ext}")],
                check=True, env=env, cwd=HERE,
            )
        print(f"{lang}: {', '.join(outputs)}")


if __name__ == "__main__":
    main()
