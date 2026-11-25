"""Navigate CLM folders and download a document in the browser worker."""
from pathlib import Path
import os
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


def default_download_directory():
    """Use the hosted file browser's workspace when it is available."""
    workspace = Path('/app/home')
    if workspace.is_dir() and os.access(workspace, os.W_OK):
        return workspace / 'Downloads'
    return Path.home() / 'Downloads'


def download_document(page, folders, filename, destination=None, report=lambda message: None, snapshot=lambda: None):
    if not folders or any(not folder.strip() for folder in folders):
        raise ValueError('Enter at least one non-empty folder name.')
    if not filename or Path(filename).name != filename or filename in ('.', '..'):
        raise ValueError('Enter a file name without a path.')
    report('Opening Documents.')
    # Dismiss only DocuSign's known introductory walkthrough, when present.
    def dismiss_walkthrough():
        close = page.locator('#walkthrough button.ux-modal__close')
        if close.is_visible():
            close.click(timeout=5000, force=True)
    dismiss_walkthrough()
    page.get_by_role('link', name='Documents', exact=True).click(timeout=30000)
    # The Documents walkthrough can appear after the page starts loading.
    try:
        page.locator('#walkthrough button.ux-modal__close').wait_for(state='visible', timeout=3000)
    except PlaywrightTimeoutError:
        pass
    dismiss_walkthrough()
    breadcrumbs = page.locator('a[aria-label^="Navigate to folder "]')
    breadcrumbs.first.wait_for(timeout=30000)
    if breadcrumbs.count() > 1:
        root_name = breadcrumbs.first.inner_text().strip()
        breadcrumbs.first.click(timeout=30000)
        page.wait_for_function("name => document.title.startsWith(name + ' - Documents')", arg=root_name, timeout=30000)
    snapshot()
    for folder in folders:
        report(f'Opening folder: {folder}')
        folder_link = page.get_by_role('row').get_by_role('link', name=folder, exact=True)
        try:
            folder_link.click(timeout=5000)
        except PlaywrightTimeoutError:
            dismiss_walkthrough()
            folder_link.click(timeout=30000)
        page.wait_for_function("name => document.title.startsWith(name + ' - Documents')", arg=folder, timeout=30000)
        snapshot()
    report('Opening document actions.')
    row = page.get_by_role('row').filter(has=page.get_by_role('link', name=filename, exact=True))
    row.locator('[aria-label="Toggle Action Menu"]').click(timeout=30000)
    snapshot()
    with page.expect_download(timeout=60000) as event:
        row.locator('[aria-label="Toggle Action Menu"]').get_by_text('Download', exact=True).click(timeout=30000)
    download = event.value
    if download.failure():
        raise ValueError('The browser could not download the file.')
    folder = Path(destination).expanduser() if destination else default_download_directory()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    if path.exists():
        stem, suffix = Path(filename).stem, Path(filename).suffix
        index = 1
        while path.exists():
            path = folder / f'{stem} ({index}){suffix}'
            index += 1
    download.save_as(str(path))
    return path
