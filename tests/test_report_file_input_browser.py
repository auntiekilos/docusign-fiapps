from playwright.sync_api import sync_playwright


def test_report_file_input_accepts_file_over_upload_label(tmp_path):
    report = tmp_path / 'report.csv'
    report.write_text('filename\nexample.pdf\n')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('''<span class="menuLabel">Upload</span>
                <input type="file" name="files[]" multiple="multiple"
                  class="fileUploadInput suppressAutoHide primaryFileUploadInput"
                  onchange="document.body.dataset.uploaded=this.files[0].name">''')
            page.locator('input[type=file].primaryFileUploadInput').set_input_files(str(report))
            assert page.locator('body').get_attribute('data-uploaded') == 'report.csv'
        finally:
            browser.close()
