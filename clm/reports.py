"""Create durable, numbered page reports before transferring them to CLM."""
import csv
import json
import os
import re
from pathlib import Path

from clm.fileparts import data_dir

FIELDS = ('zone', 'filename', 'docusign_path', 'document_url', 'document_id', 'processed_at')


def create_page_report(zone, entries):
    if not entries:
        raise ValueError('A report must contain at least one processed file.')
    if any(any(not entry.get(field) for field in FIELDS) for entry in entries):
        raise ValueError('Each report entry must include its complete DocuSign path and processing details.')
    if any(entry['zone'] != zone for entry in entries):
        raise ValueError('A report can only contain entries from its own zone.')
    safe_zone = re.sub(r'[^\w .-]', '_', zone, flags=re.UNICODE).strip(' .')
    if not safe_zone:
        raise ValueError('Zone name cannot be used in a report filename.')
    root = data_dir() / 'reports' / safe_zone
    root.mkdir(parents=True, exist_ok=True)
    # Exclusive directory creation makes the sequence durable across restarts.
    number = 1
    while True:
        folder = root / str(number)
        try:
            folder.mkdir()
            break
        except FileExistsError:
            number += 1
    filename = f'REPORT {safe_zone.upper()} {number}.csv'
    target = folder / filename
    try:
        with target.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(entries)
            stream.flush()
            os.fsync(stream.fileno())
        (folder / 'state.json').write_text(json.dumps({'status': 'pending', 'filename': filename}), encoding='utf-8')
    except BaseException:
        # Preserve the reserved sequence if a partially written file exists.
        raise
    return target
