"""Own the Playwright browser on one long-lived worker thread."""
from concurrent.futures import Future
from queue import Queue
from threading import Thread
from urllib.parse import urlsplit


def validate_url(value: str) -> str:
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
            raise ValueError
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Enter a valid HTTP or HTTPS URL without credentials.") from exc
    return value


class BrowserSession:
    def __init__(self):
        self._commands = Queue()
        self._thread = Thread(target=self._run, daemon=True, name="browser-worker")
        self._thread.start()

    def navigate(self, url: str) -> None:
        future = Future()
        self._commands.put((validate_url(url), future))
        future.result(timeout=60)

    def _run(self):
        from playwright.sync_api import sync_playwright
        playwright = None
        context = None
        while True:
            url, future = self._commands.get()
            try:
                if playwright is None:
                    playwright = sync_playwright().start()
                if context is None or not context.pages:
                    if context is not None:
                        context.close()
                    browser = playwright.chromium.launch(headless=False, args=["--no-sandbox"])
                    context = browser.new_context()
                    page = context.new_page()
                else:
                    page = context.pages[0]
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                future.set_result(None)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)
