"""Exercise filter navigation with a real browser and duplicate page controls."""
import pytest
from playwright.sync_api import sync_playwright
from clm.fileparts import select_search


def test_search_scopes_duplicate_controls_to_filters_dialog():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f'Chromium unavailable: {exc}')
        try:
            page = browser.new_page()
            page.set_content('''
                <button aria-label="search">search</button>
                <button id="all" aria-label="All filters, none applied"
                    onclick="document.getElementById('filters').hidden=false">Filters</button>
                <button onclick="window.wrong=true">Location</button>
                <div role="dialog" aria-label="All Filters" id="filters" hidden>
                  <button onclick="showMenu('type')">File Type</button>
                  <button onclick="showMenu('location')">Location</button>
                  <button onclick="document.getElementById('filters').hidden=true; document.getElementById('all').setAttribute('aria-label','All filters, filters applied')">Save</button>
                </div>
                <div role="dialog" aria-label="Filter Menu" id="menu" hidden>
                  <div id="type" hidden><button>Other</button><input aria-label="Enter Types"></div>
                  <div id="location" hidden>
                    <button data-qa="view-19ead1d3-60fb-f011-87a4-88e9a4a867b6">Clients</button>
                    <button data-qa="view-a74a8a13-effd-f011-87a4-88e9a4a867b6">Spain</button>
                    <input placeholder="Find in SPAIN"><button onclick="window.zoneSelected=true">Zona Sur</button>
                  </div>
                  <button onclick="document.getElementById('menu').hidden=true">Apply</button>
                </div>
                <script>function showMenu(name) {
                    document.getElementById('menu').hidden=false;
                    document.getElementById('type').hidden=name!=='type';
                    document.getElementById('location').hidden=name!=='location';
                }</script>
            ''')
            select_search(page, lambda _: None, 'Zona Sur')
            assert page.evaluate('window.zoneSelected === true && !window.wrong')
        finally:
            browser.close()
