"""Create durable, numbered page reports before transferring them to CLM."""
import csv
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from clm.fileparts import data_dir

FIELDS = ('zone', 'filename', 'docusign_path', 'document_url', 'document_id', 'processed_at')


def write_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.state-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(state, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)



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
    last_time = datetime.fromisoformat(entries[-1]['processed_at'].replace('Z', '+00:00'))
    if last_time.tzinfo is None:
        raise ValueError('Report timestamps must include a timezone.')
    filename = f"REPORT {safe_zone.upper()} {number} {last_time.astimezone(ZoneInfo('Europe/Madrid')):%H:%M}.csv"
    target = folder / filename
    try:
        with target.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(entries)
            stream.flush()
            os.fsync(stream.fileno())
        write_state(folder / 'state.json', {'status': 'pending', 'filename': filename})
    except BaseException:
        # Preserve the reserved sequence if a partially written file exists.
        raise
    return target

REPORT_FOLDERS = ('Users', 'Internal', 'Registro correcciones filepart')
REPORT_RETRY_SECONDS = 5 * 60


class ReportUnconfirmed(ValueError):
    pass


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
        from clm.fileparts import configured_zones
        for folder in (*REPORT_FOLDERS, configured_zones()[0]):
            dismiss()
            page.get_by_role('row').get_by_role('link', name=folder, exact=True).click(timeout=30000)
            page.locator('a[aria-label="Navigate to folder ' + folder + '"]').wait_for(timeout=30000)
        snapshot(page)
        existing = page.get_by_role('row').get_by_role('link', name=report_path.name, exact=True)
        state = report_path.parent / 'state.json'
        saved = json.loads(state.read_text(encoding='utf-8')) if state.exists() else {}
        status = saved.get('status')
        if status in ('submitted', 'uploaded'):
            if existing.count():
                write_state(state, {'status': 'uploaded', 'filename': report_path.name})
                return
            if 'retry_after' not in saved:
                saved['retry_after'] = time.time() + REPORT_RETRY_SECONDS
                write_state(state, saved)
            if time.time() < saved['retry_after']:
                raise ReportUnconfirmed(f'Report {report_path.name} is not visible yet.')
            # A fresh browser has checked the zone folder after the waiting period.
            status = 'pending'
        if existing.count():
            raise ValueError(f'Report {report_path.name} already exists in DocuSign. Check it before continuing.')
        report(f'Uploading report {report_path.name}.')
        try:
            page.get_by_role('menuitem', name='File', exact=True).click()
            upload = page.locator('input[type=file].primaryFileUploadInput')
            upload.wait_for(state='attached', timeout=30000)
            write_state(state, {'status': 'submitted', 'filename': report_path.name,
                                'retry_after': time.time() + REPORT_RETRY_SECONDS})
            upload.set_input_files(str(report_path))
            existing.wait_for(timeout=120000)
        except Exception as exc:
            raise ReportUnconfirmed(f'Report {report_path.name} was not confirmed.') from exc
        write_state(state, {'status': 'uploaded', 'filename': report_path.name})
        snapshot(page)
    finally:
        page.close()


def create_total_report(zone):
    """Create a durable total ledger from the recorded history for this zone."""
    from clm.fileparts import history_path, MAX_ATTEMPTS
    for folder in ('pending', 'page-journals'):
        directory = data_dir() / folder
        if directory.exists() and any(directory.iterdir()):
            raise ValueError('Unfinished processing records exist. Reconcile them before creating the total ledger.')
    path = history_path()
    items = []
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip():
                item = json.loads(line)
                if item.get('zone') == zone:
                    items.append({**item, 'filename': item.get('name')})
    if any(any(not item.get(field) for field in FIELDS) for item in items):
        raise ValueError('History has incomplete records. Reconcile them before creating the total ledger.')
    for item in items:
        item['status'] = 'processed'
    completed_ids = {item['document_id'] for item in items}
    attempts_dir = data_dir() / 'attempts'
    if attempts_dir.exists():
        for file in attempts_dir.glob('*.json'):
            failure = json.loads(file.read_text(encoding='utf-8'))
            if (failure['zone'] == zone and (failure.get('status') == 'upload unconfirmed' or failure['attempts'] >= MAX_ATTEMPTS)
                    and failure['document_id'] not in completed_ids):
                items.append({**failure, 'status': failure.get('status', 'could not be processed'),
                              'attempts': failure.get('upload_attempts', failure['attempts']),
                              'processed_at': failure['last_attempt_at']})
    safe_zone = re.sub(r'[^\w .-]', '_', zone, flags=re.UNICODE).strip(' .')
    if not safe_zone:
        raise ValueError('Zone name cannot be used in a report filename.')
    root = data_dir() / 'total-reports' / safe_zone
    root.mkdir(parents=True, exist_ok=True)
    target = root / f'{safe_zone.upper()} - TOTAL LEDGER.csv'
    state = root / 'state.json'
    if target.exists() and state.exists():
        return target
    try:
        with target.open('x', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=(*FIELDS, 'status', 'attempts', 'reason'), extrasaction='ignore')
            writer.writeheader()
            writer.writerows(items)
            stream.flush()
            os.fsync(stream.fileno())
        write_state(state, {'status': 'pending', 'filename': target.name})
    except FileExistsError as exc:
        raise ValueError('A total ledger already exists locally. Reconcile it before retrying.') from exc
    return target


def total_report_issue_count(report_path):
    """Count unresolved rows in the exact ledger uploaded to DocuSign."""
    with report_path.open(encoding='utf-8-sig', newline='') as stream:
        return sum(row['status'] != 'processed' for row in csv.DictReader(stream))
