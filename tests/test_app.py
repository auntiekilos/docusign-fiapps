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
        if Fake.mode == "run_fail":
            raise ValueError("Upload outcome uncertain.")
        return 1


def start(monkeypatch, mode="ok", zones="Zona Sur"):
    Fake.mode = mode
    monkeypatch.setenv("CLM_ZONES", zones)
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
    assert "1 processed. Complete" in page
    assert [b.label for b in at.button] == ["Sign in again"]


def test_login_error_stays_visible(monkeypatch):
    at = start(monkeypatch, "login_fail")
    at = at.button[0].click().run()
    assert "Sign-in was rejected." in html(at)
    assert [b.label for b in at.button] == ["Try sign-in again"]


def test_run_error_stays_visible_and_signs_out(monkeypatch):
    at = start(monkeypatch, "run_fail")
    at = at.button[0].click().run().button[0].click().run()
    assert "Stopped: Upload outcome uncertain." in html(at)
    assert [b.label for b in at.button] == ["Sign in again"]


def test_missing_zone_is_reported_without_login(monkeypatch):
    at = start(monkeypatch, zones="")
    at = at.button[0].click().run()
    assert "Set CLM_ZONES" in html(at)


def test_setup_list_has_six_fixed_slots_and_keeps_all_rows(monkeypatch):
    class Many(Fake):
        def login(self, url, progress=None):
            for i in range(9):
                progress(f"Step {i}")
            raise ValueError("Sign-in was rejected.")

    monkeypatch.setenv("CLM_ZONES", "Zona Sur")
    monkeypatch.setattr(clm.browser, "BrowserSession", Many)
    st.cache_resource.clear()
    at = AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=20).run()
    at = at.button[0].click().run()
    page = html(at)
    assert "--slots:6" in page
    assert "Starting sign-in" in page and "Step 8" in page  # oldest row is not dropped
