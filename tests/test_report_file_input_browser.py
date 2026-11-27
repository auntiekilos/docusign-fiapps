import json

import pytest
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

from clm import reports

# A reduced copy of the CLM Documents page: folder rows, breadcrumbs and the
# File menu whose Upload label is covered by a transparent file input
# (/html/body/div[5]/div[2]/div/div/ul/li[7]/span/div/ul/li[1]/input).
CLM_PAGE = '''<!doctype html><html><head><style>
  li.upload { position: relative; width: 120px; height: 24px; }
  li.upload input { position: absolute; inset: 0; opacity: 0; width: 100%; height: 100%; cursor: pointer; }
</style></head><body>
<div></div><div></div><div></div><div></div>
<div><div></div><div><div><div><ul role="menubar">
  <li></li><li></li><li></li><li></li><li></li><li></li>
  <li id="file" role="menuitem"><span class="menuLabel body-l-bold">File</span></li>
</ul></div></div></div></div>
<input id="stale" class="fileUploadInput primaryFileUploadInput" type="file" style="display:none">
<nav id="crumbs"></nav><h1 id="current"></h1><table id="rows"></table>
<script>
const options = OPTIONS;
const tree = {'Documents': ['Users'], 'Users': ['Internal'], 'Internal': ['Registro correcciones filepart'],
              'Registro correcciones filepart': ['Zona Sur'], 'Zona Sur': []};
const path = ['Documents'];
function render() {
  document.getElementById('crumbs').innerHTML = '<a aria-label="Navigate to folder Documents">Documents</a>';
  document.getElementById('current').textContent = path.at(-1);
  const rows = document.getElementById('rows');
  rows.innerHTML = '';
  for (const name of tree[path.at(-1)]) {
    const row = rows.insertRow();
    const link = document.createElement('a');
    link.href = '#'; link.textContent = name;
    link.onclick = event => { event.preventDefault(); if (tree[name]) { path.push(name); render(); } };
    row.insertCell().append(link);
  }
}
document.getElementById('stale').onchange = () => { document.body.dataset.stale = 'used'; };
document.getElementById('file').onclick = event => event.target.closest('.upload') || setTimeout(() => {
  if (!options.input) return;
  const holder = document.createElement('span');
  holder.innerHTML = `<div><ul><li class="upload"><span class="menuLabel">Upload</span>
    <input class="fileUploadInput suppressAutoHide primaryFileUploadInput" type="file" name="files[]" multiple="multiple"></li></ul></div>`;
  document.getElementById('file').append(holder);
  holder.querySelector('input').onchange = event => {
    const name = event.target.files[0].name;
    document.body.dataset.uploaded = name;
    if (options.list) setTimeout(() => { tree['Zona Sur'].push(name); render(); }, 500);
  };
}, 800);
render();
</script></body></html>'''


@pytest.fixture
def browser():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f'Chromium unavailable: {exc}')
        try:
            yield browser
        finally:
            browser.close()


def clm_page(browser, **options):
    settings = {'input': True, 'list': True, **options}
    body = CLM_PAGE.replace('OPTIONS', json.dumps(settings))
    context = browser.new_context()
    context.route('https://clm.test/**', lambda route: route.fulfill(status=200, content_type='text/html', body=body))
    search = context.new_page()
    search.goto('https://clm.test/search?aid=7')
    return search


@pytest.fixture
def fast_waits(monkeypatch):
    original = Page.wait_for_timeout
    monkeypatch.setattr(Page, 'wait_for_timeout', lambda self, ms: original(self, min(ms, 1000)))
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')


def pending_report(tmp_path):
    report = tmp_path / 'REPORT ZONA SUR 1 11:00.csv'
    report.write_text('filename\nexample.pdf\n')
    reports.write_state(tmp_path / 'state.json', {'status': 'pending', 'filename': report.name})
    return report


def state(tmp_path):
    return json.loads((tmp_path / 'state.json').read_text())['status']


def test_page_reproduces_input_intercepting_upload_hover(browser):
    page = clm_page(browser)
    page.get_by_role('menuitem', name='File', exact=True).click()
    page.wait_for_timeout(1000)
    with pytest.raises(PlaywrightTimeoutError, match='intercepts pointer events'):
        page.get_by_text('Upload', exact=True).hover(timeout=1500)


def test_report_is_sent_through_input_covering_upload_label(browser, fast_waits, tmp_path):
    search = clm_page(browser)
    report = pending_report(tmp_path)
    snapshots = []
    def capture(page):
        snapshots.append((page.locator('#current').inner_text(),
                          page.locator('#file input[type=file]').count(),
                          page.locator('body').get_attribute('data-uploaded')))
    reports.upload_report(search, report, lambda _: None, capture)
    assert any(folder == 'Users' for folder, _, _ in snapshots)
    assert any(folder == 'Zona Sur' and inputs == 1 for folder, inputs, _ in snapshots)
    assert any(uploaded == report.name for _, _, uploaded in snapshots)
    # The folder lists the report only after the overlapping input receives it.
    assert state(tmp_path) == 'uploaded'
    assert search.context.pages == [search]


def test_report_missing_from_folder_stays_submitted(browser, fast_waits, monkeypatch, tmp_path):
    monkeypatch.setattr(reports, 'REPORT_CONFIRM_MS', 2000)
    search = clm_page(browser, list=False)
    report = pending_report(tmp_path)
    with pytest.raises(reports.ReportUnconfirmed, match='was not confirmed'):
        reports.upload_report(search, report, lambda _: None, lambda _: None)
    assert state(tmp_path) == 'submitted'


def test_report_without_upload_input_is_not_marked_submitted(browser, fast_waits, monkeypatch, tmp_path):
    def short_wait(page):
        page.get_by_text('Upload', exact=True).wait_for(state='visible', timeout=1500)
    monkeypatch.setattr(reports, 'open_upload_chooser', short_wait)
    search = clm_page(browser, input=False)
    report = pending_report(tmp_path)
    with pytest.raises(reports.ReportUnconfirmed, match=r'was not sent: 0 visible of 1 upload inputs'):
        reports.upload_report(search, report, lambda _: None, lambda _: None)
    assert state(tmp_path) == 'pending'


def test_folder_click_closes_delayed_walkthrough(browser):
    from clm.reports import click_folder_with_walkthrough_retry
    page = browser.new_page()
    page.set_content('''<table><tr><td><a href="#users" onclick="document.body.dataset.opened='yes'">Users</a></td></tr></table>
    <div id="walkthrough" style="position:fixed;inset:0;z-index:10;background:rgba(0,0,0,.2)">
    <button class="ux-modal__close" onclick="document.getElementById('walkthrough').remove()">Close</button></div>''')
    click_folder_with_walkthrough_retry(page, 'Users')
    assert page.locator('body').get_attribute('data-opened') == 'yes'
    assert page.locator('#walkthrough').count() == 0


def test_report_upload_confirmation_dialog(browser, fast_waits, tmp_path):
    page = browser.new_page()
    page.set_content('''<div role="dialog">Upload report.csv
        <button onclick="document.body.dataset.confirmed='yes'">Upload</button>
    </div>''')
    messages = []
    reports.confirm_report_upload_if_prompted(page, tmp_path / 'report.csv', messages.append)
    assert page.locator('body').get_attribute('data-confirmed') == 'yes'
    assert any('confirming upload' in message for message in messages)


def test_report_confirmation_ignores_unrelated_dialog(browser, fast_waits, tmp_path):
    page = browser.new_page()
    page.set_content('''<div role="dialog">Unrelated settings
        <button onclick="document.body.dataset.clicked='yes'">Save</button>
    </div>''')
    reports.confirm_report_upload_if_prompted(page, tmp_path / 'report.csv', lambda _: None)
    assert page.locator('body').get_attribute('data-clicked') is None
