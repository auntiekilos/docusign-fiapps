"""App UI tests with a fake browser session: no network, no browser."""
from pathlib import Path

import clm.browser
import streamlit as st
from streamlit.testing.v1 import AppTest

URL = "https://clm.example.com/Documents/View?Id="


class Fake:
    mode = "ok"

    def login(self, url, progress=None):
        progress("Opening sign-in page")
        if Fake.mode == "login_fail":
            raise ValueError("Sign-in was rejected.")
        return "signed_in", None

    def process_filepart(self, progress=None, screenshot=None, event=None):
        progress("Searching")
        event({"type": "status", "message": "Page 1"})
        event({"type": "document_started", "document_id": "1", "name": "a.pdf", "url": URL + "1", "started_at": "2026-07-01T10:00:00+00:00"})
        event({"type": "document_finished", "document_id": "1", "name": "a.pdf", "url": URL + "1", "started_at": "2026-07-01T10:00:00+00:00",
               "processed_at": "2026-07-01T10:00:05+00:00", "docusign_path": None})
        event({"type": "document_started", "document_id": "2", "name": "b<i>.pdf", "url": URL + "2", "started_at": "2026-07-01T10:00:06+00:00"})
        event({"type": "document_failed", "document_id": "2", "name": "b<i>.pdf", "url": URL + "2", "started_at": "2026-07-01T10:00:06+00:00", "attempts": 2, "reason": "Download failed"})
        event({"type": "ledger_uploaded", "name": "REPORT ZONA SUR 1 12:00.csv", "uploaded_at": "2026-07-01T10:01:00+00:00"})
        event({"type": "ledger_uploaded", "name": "ZONA SUR - TOTAL LEDGER.csv", "uploaded_at": "2026-07-01T10:02:00+00:00", "issue_count": 1})
        if Fake.mode == "run_fail":
            raise ValueError("Upload outcome uncertain.")
        return 1


def start(monkeypatch, mode="ok", zones="Zona Sur"):
    Fake.mode = mode
    monkeypatch.setenv("CLM_Zone", zones)
    monkeypatch.setattr(clm.browser, "BrowserSession", Fake)
    st.cache_resource.clear()
    return AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=20).run()


def html(at):
    assert not at.exception
    return "".join(m.value for m in at.markdown)


def test_first_screen_only_setup_button_and_no_connection(monkeypatch):
    at = start(monkeypatch)
    assert [b.label for b in at.button] == ["Run setup"]
    assert "Sign in<span" not in html(at)  # nothing rendered until the user clicks


def test_sign_in_then_process_shows_real_rows(monkeypatch):
    at = start(monkeypatch)
    at = at.button[0].click().run()
    assert [b.label for b in at.button] == ["Process Zona Sur"]
    at = at.button[0].click().run()
    page = html(at)
    assert "12:00:00 CEST" in page and "12:00:05 CEST" in page  # Europe/Madrid
    assert "—" in page  # missing path
    assert "b&lt;i&gt;.pdf" in page and "Download failed (attempt 2 of 4)" in page
    assert "REPORT ZONA SUR 1 12:00.csv" in page and "12:01:00 CEST" in page
    assert "1 processed. Complete with issues" in page
    assert [b.label for b in at.button] == ["Sign in again"]


def test_login_error_stays_visible(monkeypatch):
    at = start(monkeypatch, "login_fail")
    at = at.button[0].click().run()
    assert "Sign-in was rejected." in html(at)
    assert [b.label for b in at.button] == ["Sign in again"]


def test_run_error_stays_visible_and_signs_out(monkeypatch):
    at = start(monkeypatch, "run_fail")
    at = at.button[0].click().run().button[0].click().run()
    assert "Stopped: Upload outcome uncertain." in html(at)
    assert [b.label for b in at.button] == ["Sign in again"]


def test_missing_zone_is_reported_without_login(monkeypatch):
    at = start(monkeypatch, zones="")
    at = at.button[0].click().run()
    assert "Set CLM_Zone" in html(at)


def test_main_entrypoint_survives_button_reruns(monkeypatch):
    import config
    for name in ('CLM_URL', 'CLM_USERNAME', 'CLM_PASSWORD', 'CLM_Zone', 'CLM_DATA_DIR', 'CLM_HISTORY_PATH'):
        monkeypatch.setenv(name, '')
    monkeypatch.setattr(config, 'CLM_Zone', 'Zona Sur')
    monkeypatch.setattr(clm.browser, 'BrowserSession', Fake)
    Fake.mode = 'ok'
    st.cache_resource.clear()
    at = AppTest.from_file(str(Path(__file__).parent.parent / 'main.py'), default_timeout=20).run()
    assert [b.label for b in at.button] == ['Run setup']
    at = at.button[0].click().run()
    assert not at.exception
    assert [b.label for b in at.button] == ['Process Zona Sur']
    at = at.button[0].click().run()
    assert not at.exception
    assert [b.label for b in at.button] == ['Sign in again']
    assert '1 processed.' in html(at)


def test_processing_error_details_are_visible_and_redacted(monkeypatch):
    class Failure(Fake):
        def process_filepart(self, *args):
            raise RuntimeError('diagnostic detail secret-password')
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    monkeypatch.setenv('CLM_PASSWORD', 'secret-password')
    monkeypatch.setattr(clm.browser, 'BrowserSession', Failure)
    st.cache_resource.clear()
    at = AppTest.from_file(str(Path(__file__).parent.parent / 'app.py'), default_timeout=20).run()
    at = at.button[0].click().run().button[0].click().run()
    assert not at.exception
    assert not at.code
    assert 'diagnostic detail' not in html(at)
    assert 'secret-password' not in html(at)


def test_failed_document_is_not_reported_as_clean_completion(monkeypatch):
    class OneFailure(Fake):
        def process_filepart(self, progress=None, screenshot=None, event=None):
            event({'type': 'document_failed', 'document_id': '1', 'name': 'a.pdf', 'reason': 'Download failed'})
            return 0
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    monkeypatch.setattr(clm.browser, 'BrowserSession', OneFailure)
    st.cache_resource.clear()
    at = AppTest.from_file(str(Path(__file__).parent.parent / 'app.py'), default_timeout=20).run()
    at = at.button[0].click().run().button[0].click().run()
    assert '0 processed. Complete with issues' in html(at)


def test_diagnostics_are_not_displayed(monkeypatch):
    class Logged(Fake):
        def process_filepart(self, progress=None, screenshot=None, event=None):
            assert screenshot is None
            progress('internal diagnostic detail')
            raise ValueError('Report stopped')
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    monkeypatch.setattr(clm.browser, 'BrowserSession', Logged)
    st.cache_resource.clear()
    at = AppTest.from_file(str(Path(__file__).parent.parent / 'app.py'), default_timeout=20).run()
    at = at.button[0].click().run().button[0].click().run()
    page = html(at)
    assert 'Activity log' not in page
    assert 'Browser screenshots' not in page
    assert 'internal diagnostic detail' not in page
    assert not at.code
    assert 'Stopped: Report stopped' in page
