"""Check archived evidence and published curve composition without a GPU."""
import hashlib
import json
import re
from pathlib import Path

from plot_results import published_rows

HERE = Path(__file__).resolve().parent


def main():
    manifest = json.loads((HERE / 'archive_manifest.json').read_text(encoding='utf-8'))
    for row in manifest['records']:
        path = HERE / row['path']
        assert path.is_file(), path
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row['sha256'], path
        if 'original_sha256' in row:
            migration = manifest['filename_migration']
            original = re.sub(
                re.escape(migration['suffix'].encode()) + rb'\b',
                lambda _: migration['previous_suffix'].encode(),
                path.read_bytes(),
            )
            assert hashlib.sha256(original).hexdigest() == row['original_sha256'], path
    rows = published_rows()
    assert len(rows) == 42
    keys = {(r['sorter'], r['kind'], r['condition'], r['rate']) for r in rows}
    assert len(keys) == 42
    assert len([r for r in rows if r['sorter'] == 'ks4']) == 28
    assert len([r for r in rows if r['sorter'] == 'chronosort']) == 14
    assert not any(r['sorter'] == 'chronosort' and r['condition'] == 'all_read_write' for r in rows)
    for sorter, kind, condition, rate in keys:
        assert rate in [50, 100, 200, 500, 1000, 2000, 5000]
        assert kind in ['raw', 'compressed']
    for r in rows:
        assert r['seconds'] > 0
    print(json.dumps(dict(status='passed', archived_files=len(manifest['records']), primary_curve_rows=len(rows))))


if __name__ == '__main__':
    main()
