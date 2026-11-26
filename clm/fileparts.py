"""Convert a searched filepart by downloading and uploading its bytes unchanged."""
from pathlib import Path
import json
import os
import tempfile
from datetime import datetime, timezone


def record_processed(document_id, name, zone):
    path = Path(os.environ.get('CLM_HISTORY_PATH', str(Path.home() / '.clm' / 'processed.jsonl')))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as out:
        out.write(json.dumps({'document_id': document_id, 'name': name, 'zone': zone,
                              'processed_at': datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + '\n')


def process_one(page, report, snapshot):
    from urllib.parse import parse_qs, urlsplit
    from playwright.sync_api import TimeoutError as Timeout
    close = page.locator('#walkthrough button.ux-modal__close')
    if close.is_visible():
        close.click(force=True)
    welcome = page.get_by_role('button', name='Got it', exact=True)
    if welcome.is_visible():
        welcome.click()
    report('Opening search and filtering filepart documents.')
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
    menu.get_by_role('button', name='View location', description='/F. Iniciativas Espana I Mas D Mas I/CLIENTS/').click()
    menu.get_by_role('button', name='View location', description='/F. Iniciativas Espana I Mas D Mas I/CLIENTS/SPAIN/').click()
    menu.get_by_placeholder('Find in SPAIN').fill('Zona Sur')
    menu.get_by_text('Zona Sur', exact=True).click()
    menu.get_by_role('button', name='Apply').click()
    page.get_by_role('dialog', name='All Filters').get_by_role('button', name='Save').click()
    report('Opening first Zona Sur result.')
    row = page.get_by_role('row').filter(has=page.get_by_role('button', name='Search Actions')).first
    link = row.get_by_role('link').first
    name, url = link.inner_text(), link.get_attribute('href')
    document_id = parse_qs(urlsplit(url).query).get('Id', [None])[0]
    if not document_id:
        raise ValueError('The selected result has no document ID.')
    document = page.context.new_page()
    try:
        document.goto(url, wait_until='domcontentloaded')
        snapshot(document)
        actions = document.locator('[aria-label="Actions"]')
        actions.click()
        with document.expect_download(timeout=60000) as event:
            document.get_by_role('menuitem', name='Download file').click()
        download = event.value
        if download.failure():
            raise ValueError('Document download failed.')
        with tempfile.TemporaryDirectory() as tmp:
            filename = Path(download.suggested_filename).name
            path = Path(tmp) / filename
            download.save_as(str(path))
            if not path.stat().st_size:
                raise ValueError('Downloaded document is empty.')
            report('Uploading the downloaded file as a new version.')
            actions.click()
            document.get_by_role('menuitem', name='Upload new version').click()
            dialog = document.get_by_role('dialog', name='Upload new version')
            dialog.locator('input[type=file]').set_input_files(str(path))
            dialog.get_by_role('button', name='Submit').click()
            try:
                dialog.wait_for(state='hidden', timeout=120000)
            except Timeout as exc:
                raise ValueError('Upload was submitted but completion could not be confirmed. Check CLM before retrying.') from exc
            snapshot(document)
        record_processed(document_id, name, 'Zona Sur')
        return name
    finally:
        document.close()
