"""Portable SHA-256 verification of coordinated contract-test revisions."""
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / 'backend/tests/FROZEN_TESTS.sha256').read_text(encoding='utf-8').splitlines():
    expected, name = line.split(maxsplit=1)
    # Git stores these sources with LF on all platforms (.gitattributes).
    content = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise SystemExit(f'Contract-test hash differs: {name}')
    print(f'{name}: OK')
