"""Keep Playwright operations on one long-lived worker thread."""
from concurrent.futures import Future
from queue import Queue
from threading import Thread
from urllib.parse import urlsplit
import os


def log_status(message: str) -> None:
    print("\n" * 20 + "=== DOCUSIGN CLM ===\n" + message + "\n====================" + "\n" * 20, flush=True)


def validate_url(value: str) -> str:
    value = value.strip()
    try:
        parts = urlsplit(value)
        if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
            raise ValueError
        _ = parts.port
    except ValueError as exc:
        raise ValueError("Set CLM_URL to a valid HTTPS URL without credentials.") from exc
    return value


def confirmed_login(page, on_target) -> bool:
    """Require the observed authenticated CLM shell, not a URL alone."""
    indicators = (
        page.get_by_role("button", name="profile menu"),
        page.get_by_role("link", name="Dashboard", exact=True),
        page.get_by_role("link", name="Documents", exact=True),
        page.get_by_role("link", name="Tasks", exact=True),
    )
    try:
        for indicator in indicators:
            indicator.first.wait_for(state="visible", timeout=15000)
        return on_target() and all(indicator.first.is_visible() for indicator in indicators)
    except Exception:
        return False


class BrowserSession:
    def __init__(self):
        self._commands = Queue()
        Thread(target=self._run, daemon=True, name="browser-worker").start()

    def login(self, url: str) -> str:
        try:
            url = validate_url(url)
        except ValueError as exc:
            log_status(str(exc))
            raise
        username, password = os.environ.get("CLM_USERNAME"), os.environ.get("CLM_PASSWORD")
        if not username or not password:
            message = "Set CLM_USERNAME and CLM_PASSWORD in the server environment."
            log_status(message)
            raise ValueError(message)
        log_status("Sign-in started.")
        future = Future()
        self._commands.put((url, username, password, future))
        return future.result(timeout=120)

    def _run(self):
        playwright = browser = context = None
        while True:
            url, username, password, future = self._commands.get()
            stage = "starting the browser"
            try:
                if playwright is None:
                    from playwright.sync_api import sync_playwright
                    playwright = sync_playwright().start()
                if browser is None or not browser.is_connected():
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                stage = "opening the login page"
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                target = urlsplit(url)

                def on_target():
                    actual = urlsplit(page.url)
                    return (actual.scheme, actual.hostname, actual.port or 443, actual.path) == (target.scheme, target.hostname, target.port or 443, target.path)

                def check_login_origin():
                    actual = urlsplit(page.url)
                    if actual.scheme != "https" or actual.hostname != "account-d.docusign.com" or actual.port not in (None, 443):
                        raise ValueError("Unexpected login host; credentials were not entered there.")

                if not on_target():
                    stage = "entering the email"
                    check_login_origin()
                    page.get_by_role("textbox", name="Email").fill(username, timeout=10000)
                    page.get_by_role("button", name="Next", exact=True).click(timeout=10000)
                    stage = "waiting for the password page"
                    page.locator('input[type="password"]').first.wait_for(state="visible", timeout=20000)
                    check_login_origin()
                    stage = "submitting the password"
                    page.locator('input[type="password"]').first.fill(password)
                    page.locator('button[type="submit"], input[type="submit"]').first.click(timeout=10000)
                    stage = "waiting for sign-in"
                    page.wait_for_url(lambda current: (current.scheme, current.hostname, current.port or 443, current.path) == (target.scheme, target.hostname, target.port or 443, target.path), timeout=30000)
                stage = "checking the signed-in page"
                result = "signed_in" if confirmed_login(page, on_target) else "unverified"
                log_status("Sign-in confirmed." if result == "signed_in" else "Sign-in not confirmed.")
                future.set_result(result)
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else f"Could not complete sign-in while {stage}."
                log_status(message)
                future.set_exception(ValueError(message))
            finally:
                username = password = None
