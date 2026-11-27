import pytest
from playwright.sync_api import sync_playwright, TimeoutError
from clm.fileparts import watch_upload_confirmation, wait_for_upload_confirmation


def test_transient_upload_notice_is_captured_and_errors_do_not_count():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f'Chromium unavailable: {exc}')
        try:
            page = browser.new_page()
            page.set_content('<button onclick="const n=document.createElement(\'div\');n.innerText=\'Document uploaded\';document.body.append(n);setTimeout(()=>n.remove(),50)">Submit</button>')
            watch_upload_confirmation(page)
            page.get_by_role('button', name='Submit').click()
            page.wait_for_timeout(100)
            wait_for_upload_confirmation(page, 1000)
            watch_upload_confirmation(page)
            page.evaluate("() => {const n=document.createElement('div');n.textContent='Upload failed';document.body.append(n)}")
            with pytest.raises(TimeoutError):
                wait_for_upload_confirmation(page, 200)
        finally:
            browser.close()
