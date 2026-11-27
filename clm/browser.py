"""Keep Playwright operations on one long-lived worker thread."""
from concurrent.futures import Future
from contextlib import contextmanager
import fcntl
from queue import Empty, Queue
from threading import Thread
from urllib.parse import urlsplit
import os
from datetime import datetime, timezone
import subprocess
import sys
import time
import shlex
import tempfile
from pathlib import Path


def log_status(message: str) -> None:
    print("\n" * 20 + "=== DOCUSIGN CLM ===\n" + message + "\n====================" + "\n" * 20, flush=True)


class LoginError(ValueError):
    def __init__(self, message, screenshot=None):
        super().__init__(message)
        self.screenshot = screenshot


def page_image(page):
    if page is None:
        return None
    try:
        return page.screenshot(type="png", mask=[page.locator("input, textarea, [contenteditable='true']")], timeout=5000)
    except Exception:
        return None


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


def same_origin(actual_url: str, expected_url: str) -> bool:
    try:
        actual, expected = urlsplit(actual_url), urlsplit(expected_url)
        return (actual.scheme, actual.hostname, actual.port or 443) == (expected.scheme, expected.hostname, expected.port or 443)
    except ValueError:
        return False


def wait_for_clm(page, target_url: str) -> bool:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    try:
        page.wait_for_url(lambda current: same_origin(current, target_url), timeout=30000)
        return True
    except PlaywrightTimeoutError:
        return False


def confirmed_login(page, on_target) -> bool:
    """Require the observed authenticated CLM shell, not a URL alone."""
    welcome = page.get_by_role("button", name="Got it", exact=True)
    try:
        if welcome.is_visible():
            welcome.click(timeout=5000)
    except Exception:
        pass
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


def install_user_libraries(report=log_status):
    """Resolve and unpack Debian browser libraries in a writable cache."""
    prefix = Path.home() / ".cache" / "clm-browser-libs"
    stage = "discovering browser packages"
    try:
        dry = subprocess.run([sys.executable, "-m", "playwright", "install-deps", "--dry-run", "chromium"], capture_output=True, text=True, check=True, timeout=30)
        command = next(line for line in dry.stdout.splitlines() if "apt-get install" in line)
        args = shlex.split(command)
        if "install" not in args:
            args = shlex.split(next(arg for arg in args if "apt-get install" in arg))
        packages = [arg for arg in args[args.index("install") + 1:] if not arg.startswith("-") and arg not in ("&&", ";")]
        if not packages:
            raise ValueError("No browser packages were identified")
        prefix.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            temp_path = Path(temp)
            lists = temp_path / "lists"
            (lists / "partial").mkdir(parents=True)
            apt = ["apt-get", "-o", f"Dir::State::lists={lists}"]
            stage = "refreshing the package index"
            report("Preparing a private package index (no administrator access).")
            subprocess.run([*apt, "update"], capture_output=True, check=True, timeout=120)
            stage = "resolving browser packages"
            simulation = subprocess.run([*apt, "-s", "install", "--no-install-recommends", *packages], capture_output=True, text=True, check=True, timeout=60)
            missing = [line.split()[1] for line in simulation.stdout.splitlines() if line.startswith("Inst ")]
            if not missing:
                raise ValueError("The package manager found no missing packages")
            stage = "downloading browser packages"
            report("Downloading missing browser libraries into the app cache.")
            subprocess.run([*apt, "download", *missing], cwd=temp, capture_output=True, check=True, timeout=240)
            stage = "unpacking browser packages"
            for package in temp_path.glob("*.deb"):
                subprocess.run(["dpkg-deb", "-x", str(package), str(prefix)], capture_output=True, check=True, timeout=30)
        directories = sorted({str(p.parent) for p in prefix.rglob("*.so*") if p.is_file()})
        if not directories:
            raise ValueError("Downloaded packages contained no shared libraries")
        return os.pathsep.join(directories + ([os.environ["LD_LIBRARY_PATH"]] if os.environ.get("LD_LIBRARY_PATH") else []))
    except (OSError, subprocess.SubprocessError, StopIteration, ValueError, IndexError) as exc:
        raise ValueError(f"Browser setup failed while {stage}. The host may not provide Debian package sources or network access.") from exc


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


REINDEX_WAIT_SECONDS = 10 * 60


@contextmanager
def processing_lock():
    """Allow one processing run per data directory, including across processes."""
    from clm.fileparts import data_dir

    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    # Keep the file in place: removing it could allow a second inode to be locked.
    with (root / '.processing.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError('Another run is using this data directory. Wait for it to finish.') from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


class BrowserSession:
    def __init__(self):
        self._commands = Queue()
        from clm.fileparts import start_cleanup_worker
        start_cleanup_worker()
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

    def download(self, folders, filename, destination=None, progress=None, screenshot=None):
        future, updates = Future(), Queue()
        self._commands.put(("download", folders, filename, destination, future, updates))
        deadline = time.monotonic() + 240
        while not future.done():
            if time.monotonic() >= deadline:
                raise ValueError("The download timed out.")
            try:
                kind, value = updates.get(timeout=0.5)
                if kind == "progress" and progress:
                    progress(value)
                elif kind == "screenshot" and screenshot and value:
                    screenshot(value)
            except Empty:
                pass
        while not updates.empty():
            kind, value = updates.get_nowait()
            if kind == "progress" and progress:
                progress(value)
            elif kind == "screenshot" and screenshot and value:
                screenshot(value)
        return future.result()

    def _operation(self, name, progress=None, screenshot=None, event=None):
        future, updates = Future(), Queue()
        self._commands.put((name, future, updates))
        while not future.done() or not updates.empty():
            try:
                kind, value = updates.get(timeout=0.5)
                if kind == "progress" and progress:
                    progress(value)
                elif kind == "screenshot" and screenshot and value:
                    screenshot(value)
                elif kind == "event" and event:
                    event(value)
            except Empty:
                pass
        return future.result()

    def process_filepart(self, progress=None, screenshot=None, event=None):
        from clm.fileparts import configured_zones
        configured_zones()
        with processing_lock():
            return self._process_filepart(progress, screenshot, event)

    def _process_filepart(self, progress=None, screenshot=None, event=None):
        from clm.fileparts import configured_zones
        from clm.recovery import preserve_interrupted_uploads
        preserve_interrupted_uploads(configured_zones()[0])
        from clm.reports import ReportUnconfirmed, REPORT_RETRY_SECONDS
        total = 0
        def operation_with_report_retry(name):
            while True:
                try:
                    return self._operation(name, progress, screenshot, event)
                except ReportUnconfirmed:
                    if name == "filepart":
                        raise
                    if progress:
                        progress("Report not confirmed. Waiting 5 minutes before checking it in a fresh browser.")
                    time.sleep(REPORT_RETRY_SECONDS)
                    self._operation("close", progress, screenshot)
                    result, image = self.login(os.environ.get("CLM_URL", ""), progress)
                    if screenshot and image:
                        screenshot(image)
                    if result != "signed_in":
                        raise ValueError("Sign-in not confirmed after browser restart.")
                    if name == "total":
                        self._operation("prepare_search", progress, screenshot, event)
        try:
            while True:
                count = operation_with_report_retry("filepart")
                if count > 0:
                    total += count
                if count >= 0:
                    return total
                if progress:
                    progress("Waiting 10 minutes for DocuSign before a clean search.")
                time.sleep(REINDEX_WAIT_SECONDS)
                self._operation("close", progress, screenshot)
                if progress:
                    progress("Restarting browser for a clean search.")
                result, image = self.login(os.environ.get("CLM_URL", ""), progress)
                if screenshot and image:
                    screenshot(image)
                if result != "signed_in":
                    raise ValueError("Sign-in not confirmed after browser restart.")
        finally:
            self._operation("close", progress, screenshot)

    def _run(self):
        playwright = browser = context = None
        while True:
            command = self._commands.get()
            if len(command) == 3 and command[0] == "close":
                _, future, updates = command
                try:
                    if context is not None:
                        context.close()
                    if browser is not None:
                        browser.close()
                    context = browser = None
                    future.set_result(None)
                except Exception as exc:
                    future.set_exception(ValueError("Could not close the browser session."))
                continue
            if len(command) == 3 and command[0] == "prepare_search":
                _, future, updates = command
                try:
                    from clm.fileparts import configured_zones, select_search
                    select_search(context.pages[0], lambda value: updates.put(("progress", value)), configured_zones()[0])
                    future.set_result(None)
                except Exception as exc:
                    future.set_exception(ValueError("Could not return to the zone search after restarting the browser."))
                continue
            if len(command) == 3 and command[0] == "total":
                _, future, updates = command
                try:
                    if context is None or browser is None or not browser.is_connected():
                        raise ValueError("Sign in before uploading the total ledger.")
                    from clm.fileparts import configured_zones
                    from clm.reports import create_total_report, upload_report, total_report_issue_count
                    zone = configured_zones()[0]
                    page = context.pages[0]
                    report_path = create_total_report(zone)
                    upload_report(page, report_path, lambda value: updates.put(("progress", value)),
                                  lambda current: updates.put(("screenshot", page_image(current))))
                    updates.put(("event", {"type": "ledger_uploaded", "name": report_path.name, "uploaded_at": datetime.now(timezone.utc).isoformat(), "issue_count": total_report_issue_count(report_path)}))
                    future.set_result(None)
                except Exception as exc:
                    future.set_exception(exc if isinstance(exc, ValueError) else ValueError(
                        "Total ledger upload could not be confirmed. Reconcile it before retrying."))
                continue
            if len(command) == 3 and command[0] == "filepart":
                _, future, updates = command
                try:
                    if context is None or browser is None or not browser.is_connected():
                        raise ValueError("Sign in before processing a document.")
                    from clm.fileparts import process_one
                    page = context.pages[0]
                    result = process_one(page, lambda value: updates.put(("progress", value)),
                                         lambda current: updates.put(("screenshot", page_image(current))),
                                         event=lambda value: updates.put(("event", value)))
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(exc if isinstance(exc, ValueError) else ValueError(
                        "Processing stopped. Check CLM before retrying, especially if upload was submitted."))
                continue
            if len(command) == 6 and command[0] == "download":
                _, folders, filename, destination, future, updates = command
                try:
                    if context is None or browser is None or not browser.is_connected():
                        raise ValueError("Sign in before downloading a document.")
                    from clm.documents import download_document
                    page = context.pages[0] if context.pages else context.new_page()
                    path = download_document(page, folders, filename, destination,
                                             lambda message: updates.put(("progress", message)),
                                             lambda: updates.put(("screenshot", page_image(page))))
                    future.set_result(str(path))
                except Exception as exc:
                    message = str(exc) if isinstance(exc, ValueError) else "Could not complete the document download. Check the folder and file names."
                    future.set_exception(ValueError(message))
                continue
            url, username, password, future, updates = command

            def report(message):
                log_status(message)
                updates.put(message)
            stage = "starting the browser"
            page = None
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
                        library_path = install_user_libraries(report)
                        playwright.stop()
                        os.environ["LD_LIBRARY_PATH"] = library_path
                        playwright = sync_playwright().start()
                        browser = launch_browser(playwright, report)
                    context = None
                if context is None:
                    context = browser.new_context(viewport={"width": 1920, "height": 1080})
                page = context.pages[0] if context.pages else context.new_page()
                stage = "opening the login page"
                report("Opening CLM URL.")
                page.goto(url, wait_until="domcontentloaded", timeout=45000)

                def on_target():
                    return same_origin(page.url, url)

                def check_login_origin():
                    actual = urlsplit(page.url)
                    if actual.scheme != "https" or actual.hostname not in ("account-d.docusign.com", "account.docusign.com") or actual.port not in (None, 443):
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
                    if not wait_for_clm(page, url):
                        if same_origin(page.url, "https://account-d.docusign.com"):
                            raise ValueError("Sign-in did not reach CLM. DocuSign is still showing the sign-in or verification page; login is not confirmed.")
                        raise ValueError("Sign-in did not reach the configured CLM site. Login is not confirmed.")
                stage = "checking the signed-in page"
                report("Checking whether sign-in succeeded.")
                result = "signed_in" if confirmed_login(page, on_target) else "unverified"
                log_status("Sign-in confirmed." if result == "signed_in" else "Sign-in not confirmed.")
                future.set_result((result, page_image(page)))
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else f"Could not complete sign-in while {stage}."
                log_status(message)
                future.set_exception(LoginError(message, page_image(page)))
            finally:
                username = password = None
