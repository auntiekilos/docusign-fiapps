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
REPORT_CONFIRM_MS = 120000


class ReportUnconfirmed(ValueError):
    pass


def click_folder_with_walkthrough_retry(page, folder):
    """Handle a walkthrough that appears after the folder list loads."""
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    link = page.get_by_role('row').get_by_role('link', name=folder, exact=True)
    try:
        link.click(timeout=5000)
    except PlaywrightTimeoutError:
        close = page.locator('#walkthrough button.ux-modal__close')
        if not close.is_visible():
            raise
        close.click(timeout=5000, force=True)
        link.click(timeout=30000)


UPLOAD_INPUT = 'input[type=file].primaryFileUploadInput'


def open_menu_upload_input(page):
    """Return the one file input shown over the File menu's Upload item.

    DocuSign places a transparent input on top of the Upload label. Hovering or
    clicking the label fails because the input intercepts pointer events, and
    other hidden upload inputs can exist on the page.
    """
    upload = page.locator(UPLOAD_INPUT + ':visible')
    upload.wait_for(state='visible', timeout=30000)
    return upload


def upload_input_summary(page):
    try:
        attached = page.locator(UPLOAD_INPUT).count()
        visible = page.locator(UPLOAD_INPUT + ':visible').count()
        return f'{visible} visible of {attached} upload inputs.'
    except Exception:
        return 'upload inputs could not be inspected.'


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
        report('Report: opening Documents in a new tab.')
        page.goto(documents_url, wait_until='domcontentloaded')
        report('Report: Documents page loaded; waiting for folder list.')
        snapshot(page)
        def dismiss():
            close = page.locator('#walkthrough button.ux-modal__close')
            if close.is_visible():
                report('Report: closing walkthrough popup.')
                close.click(force=True)
        dismiss()
        page.locator('a[aria-label^="Navigate to folder "]').first.wait_for(timeout=30000)
        report('Report: folder list ready.')
        from clm.fileparts import configured_zones
        folders = (*REPORT_FOLDERS, configured_zones()[0])
        for index, folder in enumerate(folders):
            dismiss()
            report(f'Report: opening folder {folder}.')
            click_folder_with_walkthrough_retry(page, folder)
            if index + 1 < len(folders):
                next_folder = folders[index + 1]
                report(f'Report: clicked {folder}; waiting for {next_folder}.')
                page.get_by_role('row').get_by_role('link', name=next_folder, exact=True).wait_for(state='visible', timeout=30000)
                report(f'Report: found {next_folder} inside {folder}.')
            else:
                report(f'Report: clicked {folder}; waiting for its heading.')
                page.get_by_role('heading', name=folder, exact=True).wait_for(state='visible', timeout=30000)
                report(f'Report: destination folder {folder} is open.')
            snapshot(page)
        report('Report: waiting seven seconds for the walkthrough.')
        page.wait_for_timeout(7000)
        dismiss()
        page.wait_for_timeout(1000)
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
            report('Report: clicking File.')
            page.get_by_role('menuitem', name='File', exact=True).click()
            report('Report: clicked File; waiting three seconds.')
            page.wait_for_timeout(3000)
            snapshot(page)
            report(f'Report: looking for upload input; {upload_input_summary(page)}')
            upload = open_menu_upload_input(page)
            report(f'Report: upload input found; {upload_input_summary(page)}')
        except Exception as exc:
            # Nothing was sent, so the report stays pending and can be sent again.
            snapshot(page)
            raise ReportUnconfirmed(f'Report {report_path.name} was not sent: {upload_input_summary(page)}') from exc
        write_state(state, {'status': 'submitted', 'filename': report_path.name,
                            'retry_after': time.time() + REPORT_RETRY_SECONDS})
        try:
            # The input covers the Upload label, so it receives the file directly.
            report('Report: sending the file to the upload input.')
            upload.set_input_files(str(report_path))
            report('Report: file sent; waiting for it to appear in the folder.')
            existing.wait_for(timeout=REPORT_CONFIRM_MS)
        except Exception as exc:
            snapshot(page)
            raise ReportUnconfirmed(f'Report {report_path.name} was not confirmed.') from exc
        write_state(state, {'status': 'uploaded', 'filename': report_path.name})
        report('Report: uploaded file is visible in the folder.')
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
