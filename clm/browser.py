"""Keep all Playwright operations on one long-lived worker thread."""
from concurrent.futures import Future
from queue import Queue
from threading import Thread
from urllib.parse import urlsplit
import os


def validate_url(value: str) -> str:
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTPS URL without credentials.") from exc
    return value


class BrowserSession:
    def __init__(self):
        self._commands = Queue()
        Thread(target=self._run, daemon=True, name="browser-worker").start()

    def login(self, url: str) -> None:
        url = validate_url(url)
        username, password = os.environ.get("CLM_USERNAME"), os.environ.get("CLM_PASSWORD")
        if not username or not password:
            raise ValueError("Set CLM_USERNAME and CLM_PASSWORD in the server environment.")
        future = Future()
        self._commands.put((url, username, password, future))
        future.result(timeout=100)

    def _run(self):
        from playwright.sync_api import sync_playwright
        playwright = browser = context = None
        while True:
            url, username, password, future = self._commands.get()
            try:
                if playwright is None:
                    playwright = sync_playwright().start()
                if browser is None or not browser.is_connected():
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                target = urlsplit(url)
                actual = urlsplit(page.url)
                if actual.scheme != "https" or actual.hostname != target.hostname or actual.port != target.port:
                    raise ValueError("Login redirected to a different origin. Credentials were not entered.")
                username_field = page.locator(os.getenv("CLM_USERNAME_SELECTOR", 'input[type="email"], input[autocomplete="username"], input[name="username"], input[name="email"]')).first
                password_field = page.locator(os.getenv("CLM_PASSWORD_SELECTOR", 'input[type="password"]')).first
                username_field.fill(username, timeout=10000)
                password_field.fill(password, timeout=10000)
                page.locator(os.getenv("CLM_SUBMIT_SELECTOR", 'button[type="submit"], input[type="submit"]')).first.click(timeout=10000)
                future.set_result(None)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                username = password = None
