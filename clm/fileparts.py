"""Process CLM filepart search results and retain downloaded copies for four hours."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
import json
import os
import shutil
import tempfile
import threading
import time

RETENTION_SECONDS = 4 * 60 * 60


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


def start_cleanup_worker():
    def run():
        while True:
            cleanup_expired()
            time.sleep(60)
    threading.Thread(target=run, name='clm-download-cleanup', daemon=True).start()


def mark_for_deletion(folder, now=None):
    deadline = (time.time() if now is None else now) + RETENTION_SECONDS
    marker = folder / 'delete-after.json'
    marker.write_text(json.dumps({'delete_after': deadline}), encoding='utf-8')


def configured_zones():
    raw = os.environ.get('CLM_ZONES', '')
    zones = [zone.strip() for zone in raw.split(',') if zone.strip()]
    if not zones:
        raise ValueError('Set CLM_ZONES to a comma-separated list of zone folder names.')
    if len(set(zones)) != len(zones):
        raise ValueError('CLM_ZONES contains duplicate zone names.')
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
        actions.click()
        with document.expect_download(timeout=60000) as event:
            document.get_by_role('menuitem', name='Download file').click()
        download = event.value
        if download.failure():
            raise ValueError('Document download failed.')
        root = data_dir() / 'downloads'
        root.mkdir(parents=True, exist_ok=True)
        folder = Path(tempfile.mkdtemp(prefix='document-', dir=root))
        path = folder / Path(download.suggested_filename).name
        download.save_as(str(path))
        download.delete()
        if not path.stat().st_size:
            raise ValueError('Downloaded document is empty.')
        report(f'Uploading: {name}')
        actions.click()
        document.get_by_role('menuitem', name='Upload new version').click()
        dialog = document.get_by_role('dialog', name='Upload new version')
        dialog.locator('input[type=file]').set_input_files(str(path))
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps({'document_id': document_id, 'name': name, 'url': url}), encoding='utf-8')
        dialog.get_by_role('button', name='Submit').click()
        try:
            dialog.wait_for(state='hidden', timeout=120000)
            document.get_by_text('Success! Your document has been checked in.', exact=True).wait_for(timeout=30000)
        except Timeout as exc:
            raise ValueError(f'Upload outcome for {name} is uncertain. Check CLM before retrying.') from exc
        mark_for_deletion(folder)
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


def process_zone(page, report, snapshot, zone, known):
    """Process each search page and repeat the search until no fileparts remain."""
    select_search(page, report, zone)
    search_url = page.url
    total = 0
    journal_dir = data_dir() / 'page-journals'
    journal_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    journal = journal_dir / (hashlib.sha256(zone.encode()).hexdigest() + '.jsonl')
    if journal.exists():
        raise ValueError(f'An unfinished page report exists for {zone}; reconcile it before retrying.')
    while True:
        batch_new = 0
        while True:
            try:
                results = page_results(page)
            except Exception:
                if page.get_by_text('0 results', exact=True).is_visible():
                    return total
                raise
            for name, url in results:
                document_id = parse_qs(urlsplit(url).query).get('Id', [None])[0]
                if document_id in known:
                    continue
                report(f'Processing {name}')
                known.add(process_document(page, name, url, zone, report, snapshot, journal))
                batch_new += 1
                total += 1
            if journal.exists():
                from clm.reports import create_page_report, upload_report
                entries = [json.loads(line) for line in journal.read_text(encoding='utf-8').splitlines() if line.strip()]
                report_path = create_page_report(zone, entries)
                upload_report(page, report_path, report, snapshot)
                journal.unlink()
            next_page = page.get_by_role('button', name='Go to next page')
            if not next_page.count() or next_page.is_disabled():
                break
            previous = results[0][1]
            next_page.click()
            page.wait_for_function("old => { const a = document.querySelector('tbody tr a[href*=\"/Documents/View?\"]'); return a && a.href !== old; }", arg=previous, timeout=30000)
        if not batch_new:
            raise ValueError('Search still returns previously processed documents. Stopped to avoid repeating uploads.')
        report('Refreshing search for remaining fileparts.')
        page.goto(search_url, wait_until='domcontentloaded')


def process_one(page, report, snapshot):
    zones = configured_zones()
    start_url = page.url
    known = processed_ids()
    total = 0
    for index, zone in enumerate(zones):
        if index:
            page.goto(start_url, wait_until='domcontentloaded')
        report(f'Starting zone {index + 1} of {len(zones)}: {zone}')
        total += process_zone(page, report, snapshot, zone, known)
    return total
