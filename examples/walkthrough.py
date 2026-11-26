import os
import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(os.environ["CLM_URL"])
    page.get_by_role("textbox", name="Email").click()
    page.get_by_role("textbox", name="Email").fill(os.environ["CLM_USERNAME"])
    page.get_by_role("button", name="Next").click()
    page.get_by_role("textbox", name="password").fill(os.environ["CLM_PASSWORD"])
    page.get_by_role("button", name="Log in", exact=True).click()
    page.locator("#walkthrough").get_by_role("button").filter(has_text=re.compile(r"^$")).click()
    page.get_by_role("button", name="search").click()
    page.get_by_role("button", name="All filters, none applied").click()
    page.get_by_role("button", name="File Type").click()
    page.get_by_role("tabpanel", name="All (198)").click()
    page.get_by_role("checkbox", name="Other").check()
    page.get_by_role("textbox", name="Enter Types").fill("filepart")
    page.get_by_role("dialog", name="Filter Menu").get_by_role("button", name="Apply").click()
    page.get_by_role("button", name="Save").click()
    page.get_by_role("button", name="All filters, filters applied").click()
    page.get_by_role("button", name="Location", exact=True).click()
    page.get_by_role("button", name="View location", description="/F. Iniciativas Espana I Mas D Mas I/CLIENTS/").click()
    page.get_by_role("button", name="View location").first.click()
    page.get_by_role("tabpanel", name="All (197)").click()
    page.get_by_role("checkbox", name="Zona Sur").uncheck()
    page.get_by_role("button", name="Apply").click()
    page.get_by_role("dialog", name="All Filters").get_by_role("button", name="Save").click()
    page.get_by_role("button", name="Search Actions", description="More Actions").click()
    page.get_by_role("menuitem", name="View Document").click(button="middle")
    page1 = context.new_page()
    page1.goto("https://eu21.springcm.com/atlas/Documents/View?aid=31310&Id=91b8b12f-67cd-4dbd-ac6b-753ba924956c")
    page1.goto("https://eu21.springcm.com/atlas/Documents/View?aid=31310&Id=91b8b12f-67cd-4dbd-ac6b-753ba924956c")
    page1.get_by_role("button", name="More info").click()
    page1.get_by_label("Actions").click()
    with page1.expect_download() as download_info:
        page1.get_by_role("menuitem", name="Download file").click()
    download = download_info.value
    page1.get_by_label("Actions").click()
    page1.get_by_role("menuitem", name="Upload new version").click()
    page1.get_by_role("button", name="Select File").click()
    page1.get_by_role("button", name="Close").click()
    page1.get_by_label("Actions").click()
    with page1.expect_download() as download1_info:
        page1.get_by_role("menuitem", name="Download file").click()
    download1 = download1_info.value

    # ---------------------
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
