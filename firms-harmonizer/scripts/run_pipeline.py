"""Cross-platform local setup, ETL and verification entry point."""
import argparse
from importlib import import_module
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*command):
    subprocess.run(command, cwd=ROOT, check=True)


def etl():
    for name in ('01_ingest_firms', '02_detect_outages_clouds', '03_train_eqm_lut'):
        run(sys.executable, str(ROOT / 'scripts' / (name + '.py')))
    builder = import_module('04_build_master_cube')
    processed = ROOT / 'data/processed'
    processed.mkdir(parents=True, exist_ok=True)
    # Validate all three outputs before replacing any published confidence cube.
    with TemporaryDirectory(prefix='.publication-', dir=processed) as temporary:
        targets = []
        for level in ('low', 'high', 'nominal'):
            name = 'fire_cube.parquet' if level == 'nominal' else f'fire_cube_{level}.parquet'
            staged = Path(temporary) / name
            builder.build_master_cube(output_path=staged, confidence_level=level)
            targets.append((staged, processed / name))
        for staged, destination in targets:
            staged.replace(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['etl', 'test', 'install'])
    args = parser.parse_args()
    if args.action == 'etl':
        etl()
    elif args.action == 'install':
        run(sys.executable, '-m', 'pip', 'install', '-r', 'requirements.lock')
        run('npm.cmd' if sys.platform == 'win32' else 'npm', 'ci', '--prefix', 'frontend')
    else:
        run(sys.executable, 'scripts/00_bootstrap_synthetic_cube.py')
        run(sys.executable, '-m', 'pytest', 'backend/tests', '-q')
        run(sys.executable, 'scripts/verify_frozen_tests.py')
        run('npm.cmd' if sys.platform == 'win32' else 'npm', 'test', '--prefix', 'frontend')
        run('npm.cmd' if sys.platform == 'win32' else 'npm', 'run', 'build', '--prefix', 'frontend')
