"""Keep Playwright operations on one long-lived worker thread."""
from concurrent.futures import Future
from queue import Empty, Queue
from threading import Thread
from urllib.parse import urlsplit
import os
import subprocess
import sys
import time
import shlex
import tempfile
from pathlib import Path


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


def install_user_libraries():
    """Extract missing Debian packages into the user's cache, without sudo."""
    prefix = Path.home() / ".cache" / "clm-browser-libs"
    try:
        dry = subprocess.run([sys.executable, "-m", "playwright", "install-deps", "--dry-run", "chromium"], capture_output=True, text=True, check=True, timeout=30)
        command = next(line for line in dry.stdout.splitlines() if "apt-get install" in line)
        args = shlex.split(command)
        if "install" not in args:
            args = shlex.split(next(arg for arg in args if "apt-get install" in arg))
        start = args.index("install") + 1
        packages = [arg for arg in args[start:] if not arg.startswith("-") and arg not in ("&&", ";")]
        simulation = subprocess.run(["apt-get", "-s", "install", "--no-install-recommends", *packages], capture_output=True, text=True, check=True, timeout=60)
        missing = [line.split()[1] for line in simulation.stdout.splitlines() if line.startswith("Inst ")]
        if not missing:
            raise ValueError("No downloadable missing packages were found.")
        prefix.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["apt-get", "download", *missing], cwd=temp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=240)
            for package in Path(temp).glob("*.deb"):
                subprocess.run(["dpkg-deb", "-x", str(package), str(prefix)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=30)
        directories = sorted({str(p.parent) for p in prefix.rglob("*.so*") if p.is_file()})
        if not directories:
            raise ValueError("No shared libraries were extracted.")
        return os.pathsep.join(directories + ([os.environ["LD_LIBRARY_PATH"]] if os.environ.get("LD_LIBRARY_PATH") else []))
    except (OSError, subprocess.SubprocessError, StopIteration, ValueError, IndexError) as exc:
        raise ValueError("Could not prepare browser libraries in the app environment.") from exc


def launch_browser(playwright, report=log_status):
    """Install Playwright's matching headless browser if it is not present."""
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        detail = str(exc)
        if "Executable doesn't exist" in detail:
            report("Installing the browser needed for sign-in. This may take a few minutes.")
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "--only-shell", "chromium"],
                    check=True, timeout=300, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except (subprocess.SubprocessError, OSError) as error:
                raise ValueError("Browser download failed. The host must allow Playwright's Chromium download.") from error
            try:
                return playwright.chromium.launch(headless=True)
            except Exception as error:
                detail = str(error)
        if "Host system is missing dependencies" in detail or "error while loading shared libraries" in detail:
            raise RuntimeError("missing_browser_libraries") from exc
        raise ValueError("The headless browser could not start. Check the host's Chromium installation and system libraries.") from exc


class BrowserSession:
    def __init__(self):
        self._commands = Queue()
        Thread(target=self._run, daemon=True, name="browser-worker").start()

    def login(self, url: str, progress=None) -> str:
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
        updates = Queue()
        self._commands.put((url, username, password, future, updates))
        deadline = time.monotonic() + 480
        while not future.done():
            if time.monotonic() >= deadline:
                raise ValueError("Browser setup or sign-in timed out. Check the server logs.")
            try:
                message = updates.get(timeout=0.5)
                if progress:
                    progress(message)
            except Empty:
                pass
        return future.result()

    def _run(self):
        playwright = browser = context = None
        while True:
            url, username, password, future, updates = self._commands.get()

            def report(message):
                log_status(message)
                updates.put(message)
            stage = "starting the browser"
            try:
                report("Starting headless browser.")
                if playwright is None:
                    from playwright.sync_api import sync_playwright
                    playwright = sync_playwright().start()
                if browser is None or not browser.is_connected():
                    try:
                        browser = launch_browser(playwright, report)
                    except RuntimeError as exc:
                        if str(exc) != "missing_browser_libraries":
                            raise
                        report("Preparing browser libraries without administrator access.")
                        library_path = install_user_libraries()
                        playwright.stop()
                        os.environ["LD_LIBRARY_PATH"] = library_path
                        playwright = sync_playwright().start()
                        browser = launch_browser(playwright, report)
                    context = None
                if context is None:
                    context = browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                stage = "opening the login page"
                report("Opening CLM URL.")
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
                    report("Entering username and selecting Next.")
                    page.get_by_role("textbox", name="Email").fill(username, timeout=10000)
                    page.get_by_role("button", name="Next", exact=True).click(timeout=10000)
                    stage = "waiting for the password page"
                    page.locator('input[type="password"]').first.wait_for(state="visible", timeout=20000)
                    check_login_origin()
                    stage = "submitting the password"
                    report("Entering password and submitting sign-in.")
                    page.locator('input[type="password"]').first.fill(password)
                    page.locator('button[type="submit"], input[type="submit"]').first.click(timeout=10000)
                    stage = "waiting for sign-in"
                    page.wait_for_url(lambda current: (current.scheme, current.hostname, current.port or 443, current.path) == (target.scheme, target.hostname, target.port or 443, target.path), timeout=30000)
                stage = "checking the signed-in page"
                report("Checking whether sign-in succeeded.")
                result = "signed_in" if confirmed_login(page, on_target) else "unverified"
                log_status("Sign-in confirmed." if result == "signed_in" else "Sign-in not confirmed.")
                future.set_result(result)
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else f"Could not complete sign-in while {stage}."
                log_status(message)
                future.set_exception(ValueError(message))
            finally:
                username = password = None
