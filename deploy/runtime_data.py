"""Publish validated runtime data as a private image in the existing image registry."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from publish import runtime_files
from cloudrun import run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, help='Registry image name including a version tag')
    args = parser.parse_args()
    run('gcloud', 'auth', 'configure-docker', args.image.split('/')[0], '--quiet')
    files = runtime_files()
    manifest = {'files': {name: path.stat().st_mtime_ns for name, path in files.items()}}
    checksums = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()}
    with TemporaryDirectory(prefix='firms-runtime-data-') as directory:
        root = Path(directory)
        for name, source in files.items():
            destination = root / 'data' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        (root/'data/manifest.json').write_text(json.dumps(manifest, sort_keys=True), encoding='utf-8')
        (root/'data/checksums.json').write_text(json.dumps(checksums, sort_keys=True), encoding='utf-8')
        (root/'Dockerfile').write_text('FROM scratch\nCOPY data/ /data/\nCMD ["/data-only-image"]\n', encoding='utf-8')
        subprocess.run(['docker', 'build', '--platform=linux/amd64', '-t', args.image, str(root)], check=True)
        subprocess.run(['docker', 'push', args.image], check=True)
    print(f'Published {len(files)} runtime files to {args.image}. Pin its digest in RUNTIME_DATA_IMAGE.')


if __name__ == '__main__':
    main()
