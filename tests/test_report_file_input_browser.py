from playwright.sync_api import sync_playwright


def test_report_file_input_accepts_file_over_upload_label(tmp_path):
    report = tmp_path / 'report.csv'
    report.write_text('filename\nexample.pdf\n')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('''<span class="menuLabel" onmouseenter="if(!document.querySelector('input')){const f=document.createElement('input');f.type='file';f.name='files[]';f.multiple=true;f.className='fileUploadInput suppressAutoHide primaryFileUploadInput';f.onchange=()=>document.body.dataset.uploaded=f.files[0].name;document.body.append(f)}">Upload</span>''')
            page.get_by_text('Upload', exact=True).hover()
            page.locator('input[type=file].primaryFileUploadInput').set_input_files(str(report))
            assert page.locator('body').get_attribute('data-uploaded') == 'report.csv'
        finally:
            browser.close()


def test_folder_click_closes_delayed_walkthrough():
    from clm.reports import click_folder_with_walkthrough_retry
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('''<table><tr><td><a href="#users" onclick="document.body.dataset.opened='yes'">Users</a></td></tr></table>
            <div id="walkthrough" style="position:fixed;inset:0;z-index:10;background:rgba(0,0,0,.2)">
            <button class="ux-modal__close" onclick="document.getElementById('walkthrough').remove()">Close</button></div>''')
            click_folder_with_walkthrough_retry(page, 'Users')
            assert page.locator('body').get_attribute('data-opened') == 'yes'
            assert page.locator('#walkthrough').count() == 0
        finally:
            browser.close()
