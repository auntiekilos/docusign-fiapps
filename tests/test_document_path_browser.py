import pytest
from playwright.sync_api import sync_playwright
from clm.fileparts import document_path


def test_breadcrumb_waits_for_overflow_and_menu_entries():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f'Chromium unavailable: {exc}')
        try:
            page = browser.new_page()
            page.set_content('''<nav><ol><li><button aria-label="Ancestor subfolders overflow menu"
              data-qa="DocPreviewBreadcrumbs__FolderOverflowMenuButton" onclick="showPath()">...</button></li></ol></nav>
              <div role="menu" id="path" hidden></div>
              <script>function showPath(){const p=document.querySelector('#path');
                if(!p.hidden){p.hidden=true;return;} p.hidden=false;
                setTimeout(()=>p.innerHTML='<div role="menuitem">CLIENTS</div><div role="menuitem">SPAIN</div><div role="menuitem">Zona Centro</div><div role="menuitem">Client</div><div role="menuitem">NDA</div>',100);
              }</script>''')
            assert document_path(page, 'example.pdf', 'Zona Centro') == 'CLIENTS/SPAIN/Zona Centro/Client/NDA'
        finally:
            browser.close()
