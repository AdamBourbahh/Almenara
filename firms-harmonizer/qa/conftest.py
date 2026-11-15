"""Standalone real-archive audit; deliberately outside synthetic backend fixtures."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['USE_SYNTHETIC_CUBE'] = '0'
os.environ['COPILOT_OFFLINE'] = '1'
os.environ['REQUEST_RATE_MULTIPLIER'] = '10000'
RECORDS = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == 'call':
        record = dict(getattr(item, 'audit', {}))
        record.update(case=item.nodeid, result='passed' if report.passed else 'blocked' if report.skipped else 'failed')
        if report.failed:
            record['failure'] = str(report.longrepr)
        RECORDS.append(record)


def pytest_sessionfinish(session, exitstatus):
    output = Path(os.getenv('COPILOT_QA_OUTPUT', ROOT.parent / 'docs/verification/2026-11-15-copilot-quality/archive.json'))
    files = []
    for name in ['fire_cube.parquet', 'staged_firms.parquet']:
        path = ROOT / 'data/processed' / name
        if path.exists():
            files.append({'path': str(path.relative_to(ROOT)), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'provenance': 'real FIRMS inputs; locally rebuilt'})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'files': files, 'records': RECORDS}, indent=2, default=str))
