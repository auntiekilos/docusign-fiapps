"""Create durable, numbered page reports before transferring them to CLM."""
import csv
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

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

REPORT_FOLDERS = ('Users', 'Internal', 'Registro correcciones filepart')


def upload_report(search_page, report_path, report, snapshot):
    """Upload from an independent tab, stopping if the result is ambiguous."""
    page = search_page.context.new_page()
    try:
        parts = urlsplit(search_page.url)
        account = parse_qs(parts.query).get('aid', [])
        if not account:
            raise ValueError('The search page has no DocuSign account ID.')
        documents_url = urlunsplit((parts.scheme, parts.netloc, '/atlas/Documents/BrowseDocuments.aspx',
                                   urlencode({'aid': account[0]}), ''))
        page.goto(documents_url, wait_until='domcontentloaded')
        def dismiss():
            close = page.locator('#walkthrough button.ux-modal__close')
            if close.is_visible():
                close.click(force=True)
        dismiss()
        page.locator('a[aria-label^="Navigate to folder "]').first.wait_for(timeout=30000)
        for folder in REPORT_FOLDERS:
            dismiss()
            page.get_by_role('row').get_by_role('link', name=folder, exact=True).click(timeout=30000)
            page.locator('a[aria-label="Navigate to folder ' + folder + '"]').wait_for(timeout=30000)
        snapshot(page)
        existing = page.get_by_role('row').get_by_role('link', name=report_path.name, exact=True)
        if existing.count():
            raise ValueError(f'Report {report_path.name} already exists in DocuSign. Check it before continuing.')
        report(f'Uploading report {report_path.name}.')
        page.get_by_role('menuitem', name='File', exact=True).click()
        page.locator('li.fileUploadButton input[type=file]').set_input_files(str(report_path))
        existing.wait_for(timeout=120000)
        state = report_path.parent / 'state.json'
        state.write_text(json.dumps({'status': 'uploaded', 'filename': report_path.name}), encoding='utf-8')
        snapshot(page)
    finally:
        page.close()
