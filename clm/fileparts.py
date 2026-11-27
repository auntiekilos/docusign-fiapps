"""Process CLM filepart search results and retain downloaded copies for four hours."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
import json
import errno
import hashlib
import os
import shutil
import tempfile
import threading
import time

RETENTION_SECONDS = 4 * 60 * 60
UNCONFIRMED_RETENTION_SECONDS = 2 * 60
MAX_ATTEMPTS = 4  # More than three attempts means four total attempts.
UPLOAD_CONFIRM_SECONDS = 45
TEST_DOCUMENT_LIMIT = 10
DOWNLOAD_RETRY_SECONDS = 10 * 60


class DownloadFailed(ValueError):
    """All permitted download attempts failed and were recorded."""


class UploadUnconfirmed(ValueError):
    """The upload was submitted but its outcome was not confirmed."""


def data_dir():
    return Path(os.environ.get('CLM_DATA_DIR', str(Path.home() / '.clm')))


def history_path():
    return Path(os.environ.get('CLM_HISTORY_PATH', str(data_dir() / 'processed.jsonl')))


def record_processed(document_id, name, zone, url=None, docusign_path=None, processed_at=None):
    path = history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps({'document_id': document_id, 'name': name, 'zone': zone,
                              'processed_at': processed_at or datetime.now(timezone.utc).isoformat(), 'document_url': url,
                              'docusign_path': docusign_path}, ensure_ascii=False) + '\n')


def processed_ids():
    path = history_path()
    if not path.exists():
        return set()
    return {json.loads(line)['document_id'] for line in path.read_text(encoding='utf-8').splitlines() if line.strip()}



def attempt_path(zone, document_id):
    key = hashlib.sha256((zone + "\0" + document_id).encode()).hexdigest()
    return data_dir() / 'attempts' / (key + '.json')


def read_attempt(zone, document_id):
    path = attempt_path(zone, document_id)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def record_failure(zone, document_id, name, url, reason, *, unconfirmed=False):
    try:
        return _record_failure(zone, document_id, name, url, reason, unconfirmed=unconfirmed)
    except OSError as exc:
        if exc.errno != errno.ENOSPC:
            raise
        cleanup_confirmed_downloads()
        return _record_failure(zone, document_id, name, url, reason, unconfirmed=unconfirmed)


def _record_failure(zone, document_id, name, url, reason, *, unconfirmed=False):
    path = attempt_path(zone, document_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = read_attempt(zone, document_id) or {}
    entry = {'zone': zone, 'document_id': document_id, 'filename': name,
             'document_url': url, 'attempts': previous.get('attempts', 0) + 1,
             'reason': str(reason), 'last_attempt_at': datetime.now(timezone.utc).isoformat()}
    if unconfirmed:
        entry.update(status='upload unconfirmed', upload_attempts=1)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.attempt-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(entry, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return entry

def cleanup_expired(now=None):
    now = time.time() if now is None else now
    root = data_dir() / 'downloads'
    if not root.exists():
        return
    for marker in root.glob('*/delete-after.json'):
        try:
            entry = json.loads(marker.read_text(encoding='utf-8'))
            if now >= entry['delete_after']:
                shutil.rmtree(marker.parent)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f'Unable to clean retained download {marker.parent.name}: {type(exc).__name__}', flush=True)


def cleanup_confirmed_downloads():
    """Free local copies only when a successful upload has a valid marker."""
    root = data_dir() / 'downloads'
    for marker in root.glob('*/delete-after.json'):
        try:
            entry = json.loads(marker.read_text(encoding='utf-8'))
            if entry.get('status', 'confirmed') != 'confirmed' or not isinstance(entry['delete_after'], (int, float)):
                continue
            shutil.rmtree(marker.parent)
        except FileNotFoundError:
            continue
        except (ValueError, KeyError, TypeError):
            continue


def download_for_upload(document, actions, name, zone, document_id, url, report):
    """Retry this document in place, preserving unconfirmed uploads on disk."""
    previous = read_attempt(zone, document_id) or {}
    for _ in range(previous.get('attempts', 0), MAX_ATTEMPTS):
        folder = None
        download = None
        try:
            actions.click()
            with document.expect_download(timeout=60000) as event:
                document.get_by_role('menuitem', name='Download file').click()
            download = event.value
            if download.failure():
                raise ValueError('The browser could not download the document.')
            root = data_dir() / 'downloads'
            root.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix='document-', dir=root))
            path = folder / Path(download.suggested_filename).name
            download.save_as(str(path))
            if not path.stat().st_size:
                raise ValueError('Downloaded document is empty.')
            download.delete()
            return folder, path
        except Exception as exc:
            if download is not None:
                try:
                    download.delete()
                except Exception:
                    pass
            if folder is not None:
                shutil.rmtree(folder, ignore_errors=True)
            cleanup_confirmed_downloads()
            failure = record_failure(zone, document_id, name, url,
                                     f'Download failed: {type(exc).__name__}')
            if failure['attempts'] >= MAX_ATTEMPTS:
                raise DownloadFailed(failure['reason']) from exc
            report(f"Download failed for {name} (attempt {failure['attempts']} of {MAX_ATTEMPTS}). Waiting 10 minutes before retrying.")
            time.sleep(DOWNLOAD_RETRY_SECONDS)
    raise DownloadFailed('Download attempts exhausted.')


def start_cleanup_worker():
    def run():
        while True:
            cleanup_expired()
            time.sleep(60)
    threading.Thread(target=run, name='clm-download-cleanup', daemon=True).start()


def mark_for_deletion(folder, now=None, *, confirmed=True):
    retention = RETENTION_SECONDS if confirmed else UNCONFIRMED_RETENTION_SECONDS
    deadline = (time.time() if now is None else now) + retention
    marker = folder / 'delete-after.json'
    marker.write_text(json.dumps({'delete_after': deadline, 'status': 'confirmed' if confirmed else 'unconfirmed'}), encoding='utf-8')


def configured_zones():
    raw = os.environ.get('CLM_Zone', '')
    zones = [zone.strip() for zone in raw.split(',') if zone.strip()]
    if not zones:
        raise ValueError('Set CLM_Zone to one zone folder name.')
    if len(zones) != 1:
        raise ValueError('Configure exactly one zone in CLM_Zone per installation.')
    return zones


def select_search(page, report, zone):
    close = page.locator('#walkthrough button.ux-modal__close')
    if close.is_visible():
        close.click(force=True)
    welcome = page.get_by_role('button', name='Got it', exact=True)
    if welcome.is_visible():
        welcome.click()
    report(f'Searching for filepart documents in {zone}.')
    page.get_by_role('button', name='search', exact=True).click()
    page.get_by_role('button', name='All filters, none applied').click()
    page.get_by_role('button', name='File Type', exact=True).click()
    menu = page.get_by_role('dialog', name='Filter Menu')
    menu.get_by_text('Other', exact=True).click()
    menu.get_by_role('textbox', name='Enter Types').fill('filepart')
    menu.get_by_role('button', name='Apply').click()
    page.get_by_role('dialog', name='All Filters').get_by_role('button', name='Save').click()
    page.get_by_role('button', name='All filters, filters applied').click()
    page.get_by_role('button', name='Location', exact=True).click()
    menu = page.get_by_role('dialog', name='Filter Menu')
    menu.locator("button[data-qa='view-19ead1d3-60fb-f011-87a4-88e9a4a867b6']").click()
    menu.locator("button[data-qa='view-a74a8a13-effd-f011-87a4-88e9a4a867b6']").click()
    menu.get_by_placeholder('Find in SPAIN').fill(zone)
    menu.get_by_text(zone, exact=True).click()
    menu.get_by_role('button', name='Apply').click()
    page.get_by_role('dialog', name='All Filters').get_by_role('button', name='Save').click()


def page_results(page):
    links = page.locator('tbody tr a[href*="/Documents/View?"]')
    links.first.wait_for(timeout=30000)
    return [(link.inner_text().strip(), link.get_attribute('href')) for link in links.all()]


def process_document(page, name, url, zone, report, snapshot, journal=None):
    from playwright.sync_api import TimeoutError as Timeout
    document_id = parse_qs(urlsplit(url).query).get('Id', [None])[0]
    if not document_id:
        raise ValueError('A search result has no document ID.')
    pending = data_dir() / 'pending' / (document_id + '.json')
    if pending.exists():
        raise ValueError(f'An earlier upload for {name} has an uncertain outcome. Check CLM before retrying.')
    document = page.context.new_page()
    folder = None
    confirmed = False
    try:
        document.goto(url, wait_until='domcontentloaded')
        snapshot(document)
        breadcrumb = document.get_by_role('navigation', name='Breadcrumb')
        overflow = breadcrumb.get_by_role('button', name='Ancestor subfolders overflow menu')
        folders = []
        if overflow.is_visible():
            overflow.click()
            folders = document.get_by_role('menu', name='Ancestor subfolders overflow menu').get_by_role('menuitem').all_text_contents()
            overflow.click()
        else:
            folders = [text.strip() for text in breadcrumb.locator('li').all_text_contents() if text.strip()]
            folders = [part for part in folders if part != name]
        if not folders:
            raise ValueError(f'Could not determine the DocuSign path for {name}.')
        docusign_path = '/'.join(part.strip() for part in folders if part.strip())
        actions = document.locator('[aria-label="Actions"]')
        folder, path = download_for_upload(document, actions, name, zone, document_id, url, report)
        report(f'Uploading: {name}')
        actions.click()
        document.get_by_role('menuitem', name='Upload new version').click()
        dialog = document.get_by_role('dialog', name='Upload new version')
        dialog.locator('input[type=file]').set_input_files(str(path))
        mark_for_deletion(folder, confirmed=False)
        pending.parent.mkdir(parents=True, exist_ok=True)
        # Keep the record durable before submitting; a crash must not silently retry.
        with pending.open('w', encoding='utf-8') as stream:
            json.dump({'document_id': document_id, 'name': name, 'url': url,
                       'upload_attempt': 1}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        deadline = time.monotonic() + UPLOAD_CONFIRM_SECONDS
        try:
            dialog.get_by_role('button', name='Submit').click(timeout=UPLOAD_CONFIRM_SECONDS * 1000)
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            document.get_by_text('Success! Your document has been checked in.', exact=True).wait_for(timeout=remaining)
        except Timeout as exc:
            raise UploadUnconfirmed(f'Upload of {name} was not confirmed within 45 seconds.') from exc
        mark_for_deletion(folder)
        confirmed = True
        processed_at = datetime.now(timezone.utc).isoformat()
        entry = {'zone': zone, 'filename': name, 'docusign_path': docusign_path,
                 'document_url': url, 'document_id': document_id, 'processed_at': processed_at}
        if journal is not None:
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
        record_processed(document_id, name, zone, url, docusign_path, processed_at)
        pending.unlink()
        snapshot(document)
        return document_id
    finally:
        document.close()
        # A copy is needed only after confirmation or when submission is uncertain.
        if folder is not None and not pending.exists() and not confirmed:
            shutil.rmtree(folder, ignore_errors=True)


def finish_page_report(page, journal, zone, known, report, snapshot, event=None):
    from clm.reports import create_page_report, upload_report, write_state
    manifest = journal.with_suffix('.report.json')
    if not journal.exists():
        manifest.unlink(missing_ok=True)
        return
    entries = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines() if line.strip()]
    digest = hashlib.sha256(journal.read_bytes()).hexdigest()
    if manifest.exists():
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        if saved['digest'] != digest:
            raise ValueError('Page records changed after report preparation. Check the report before continuing.')
        report_path = Path(saved['path'])
    else:
        report_path = create_page_report(zone, entries)
        write_state(manifest, {'digest': digest, 'path': str(report_path)})
    upload_report(page, report_path, report, snapshot)
    # A crash may occur between recording the page and appending global history.
    recorded = processed_ids()
    for entry in entries:
        if entry['document_id'] not in recorded:
            record_processed(entry['document_id'], entry['filename'], entry['zone'],
                             entry['document_url'], entry['docusign_path'], entry['processed_at'])
            recorded.add(entry['document_id'])
        known.add(entry['document_id'])
    if event:
        event({'type': 'ledger_uploaded', 'name': report_path.name, 'uploaded_at': datetime.now(timezone.utc).isoformat()})
    journal.unlink()
    manifest.unlink(missing_ok=True)


def process_zone(page, report, snapshot, zone, known, event=None):
    """Process each search page and repeat the search until no fileparts remain."""
    select_search(page, report, zone)
    search_url = page.url
    total = 0
    journal_dir = data_dir() / 'page-journals'
    journal_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    journal = journal_dir / (hashlib.sha256(zone.encode()).hexdigest() + '.jsonl')
    finish_page_report(page, journal, zone, known, report, snapshot, event)
    while True:
        batch_new = 0
        retry_needed = False
        exhausted_seen = False
        known_seen = False
        while True:
            try:
                results = page_results(page)
            except Exception:
                if page.get_by_text('0 results', exact=True).is_visible():
                    return total
                raise
            for name, url in results:
                document_id = parse_qs(urlsplit(url).query).get('Id', [None])[0]
                if not document_id:
                    raise ValueError('A search result has no document ID.')
                if document_id in known:
                    known_seen = True
                    continue
                previous = read_attempt(zone, document_id)
                if previous and (previous.get('status') == 'upload unconfirmed' or previous['attempts'] >= MAX_ATTEMPTS):
                    exhausted_seen = True
                    continue
                report(f'Processing {name}')
                started_at = datetime.now(timezone.utc).isoformat()
                if event:
                    event({'type': 'document_started', 'document_id': document_id, 'name': name, 'url': url, 'started_at': started_at})
                try:
                    processed = process_document(page, name, url, zone, report, snapshot, journal)
                except DownloadFailed as exc:
                    failed = read_attempt(zone, document_id)
                    exhausted_seen = True
                    report(f"Could not download {name} after {failed['attempts']} attempts.")
                    if event:
                        event({'type': 'document_failed', 'document_id': document_id, 'name': name,
                               'url': url, 'started_at': started_at, 'attempts': failed['attempts'],
                               'max_attempts': MAX_ATTEMPTS, 'reason': str(exc)})
                    continue
                except UploadUnconfirmed as exc:
                    failed = record_failure(zone, document_id, name, url, exc, unconfirmed=True)
                    # The failure record is durable before removing the pending marker.
                    (data_dir() / 'pending' / (document_id + '.json')).unlink()
                    exhausted_seen = True
                    report(f'Upload of {name} unconfirmed; check DocuSign before retrying.')
                    if event:
                        event({'type': 'document_failed', 'document_id': document_id, 'name': name,
                               'url': url, 'started_at': started_at, 'attempts': 1,
                               'max_attempts': 1, 'reason': str(exc)})
                    continue
                except ValueError as exc:
                    # Once an upload is submitted, its outcome must be reconciled by a person.
                    if (data_dir() / 'pending' / (document_id + '.json')).exists():
                        raise
                    failed = record_failure(zone, document_id, name, url, exc)
                    exhausted_seen |= failed['attempts'] >= MAX_ATTEMPTS
                    retry_needed |= failed['attempts'] < MAX_ATTEMPTS
                    report(f"Could not process {name} (attempt {failed['attempts']} of {MAX_ATTEMPTS}).")
                    if event:
                        event({'type': 'document_failed', 'document_id': document_id, 'name': name, 'url': url, 'started_at': started_at, 'attempts': failed['attempts'], 'reason': str(exc)})
                    continue
                known.add(processed)
                if event:
                    records = [json.loads(line) for line in history_path().read_text(encoding='utf-8').splitlines() if line.strip()]
                    item = next((r for r in reversed(records) if r.get('document_id') == document_id and r.get('zone') == zone), None)
                    if item is None:
                        raise ValueError('Processed document is missing from history. Reconcile before continuing.')
                    event({'type': 'document_finished', 'document_id': document_id, 'name': name, 'url': url, 'started_at': started_at, 'processed_at': item['processed_at'], 'docusign_path': item['docusign_path']})
                attempt_path(zone, document_id).unlink(missing_ok=True)
                batch_new += 1
                total += 1
                if total >= TEST_DOCUMENT_LIMIT:
                    break
            finish_page_report(page, journal, zone, known, report, snapshot, event)
            if total >= TEST_DOCUMENT_LIMIT:
                report(f'Test limit of {TEST_DOCUMENT_LIMIT} documents reached.')
                return total
            next_page = page.get_by_role('button', name='Go to next page')
            if not next_page.count() or next_page.is_disabled():
                break
            previous = results[0][1]
            next_page.click()
            page.wait_for_function("old => { const a = document.querySelector('tbody tr a[href*=\"/Documents/View?\"]'); return a && a.href !== old; }", arg=previous, timeout=30000)
        if total:
            return total
        if retry_needed:
            return -1
        if known_seen or exhausted_seen:
            return 0
        raise ValueError('No results could be verified.')


def process_one(page, report, snapshot, event=None):
    zones = configured_zones()
    start_url = page.url
    known = processed_ids()
    total = 0
    for index, zone in enumerate(zones):
        if index:
            page.goto(start_url, wait_until='domcontentloaded')
        report(f'Starting zone {index + 1} of {len(zones)}: {zone}')
        if event is None:
            total += process_zone(page, report, snapshot, zone, known)
        else:
            total += process_zone(page, report, snapshot, zone, known, event=event)
    return total
