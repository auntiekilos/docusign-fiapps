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
            page.route('https://upload.test/**', lambda route: route.fulfill(status=200, content_type='text/html', body='<html><body>Reloaded</body></html>'))
            page.goto('https://upload.test/start')
            page.set_content('<button onclick="const n=document.createElement(\'div\');n.innerText=\'Document uploaded\';document.body.append(n);setTimeout(()=>n.remove(),50)">Submit</button>')
            key = watch_upload_confirmation(page)
            page.get_by_role('button', name='Submit').click()
            page.wait_for_timeout(100)
            page.goto('https://upload.test/reloaded')
            wait_for_upload_confirmation(page, 1000, key)
            key = watch_upload_confirmation(page)
            page.evaluate("() => {const n=document.createElement('div');n.textContent='Upload failed';document.body.append(n)}")
            with pytest.raises(TimeoutError):
                wait_for_upload_confirmation(page, 200, key)
        finally:
            browser.close()


def test_notice_rendered_during_reload_is_captured():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f'Chromium unavailable: {exc}')
        try:
            page = browser.new_page()
            page.route('https://upload.test/**', lambda route: route.fulfill(status=200, content_type='text/html', body='<html><body><div>Document uploaded</div></body></html>' if route.request.url.endswith('/result') else '<html><body>Ready</body></html>'))
            page.goto('https://upload.test/start')
            key = watch_upload_confirmation(page)
            page.goto('https://upload.test/result')
            wait_for_upload_confirmation(page, 1000, key)
        finally:
            browser.close()
