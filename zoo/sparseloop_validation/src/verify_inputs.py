"""Verify sealed snapshots without reading any external input."""
import hashlib
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]
inputs=root/'inputs'
manifest=json.loads((inputs/'snapshot_manifest.json').read_text())
for name,entry in manifest['files'].items():
    assert hashlib.sha256((inputs/name).read_bytes()).hexdigest()==entry['sha256'],name
print(json.dumps({'files_verified':len(manifest['files']),'real_cases':manifest['real_cases'],
                  'snapshot_sha256':hashlib.sha256((inputs/'snapshot_manifest.json').read_bytes()).hexdigest()}))
