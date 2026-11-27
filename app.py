"""Document processing interface."""
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
import os

import streamlit as st

from clm.logging_file import redact, write_log
from clm.browser import BrowserSession
from clm.fileparts import configured_zones

st.set_page_config(page_title="CLM progress", layout="wide", initial_sidebar_state="collapsed")

CSS = """<style>
#MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"] {display:none!important;}
.block-container {max-width:100%;padding:1rem;}
.stage {position:fixed;top:0;left:0;right:0;bottom:16rem;padding:1rem;}
.stage-in {height:100%;display:flex;flex-direction:column;}
.hdr {display:flex;justify-content:space-between;padding:.5rem;font-weight:600;}
.wrap {overflow:auto;border:1px solid #d0d0d0;flex:1;}
table.docs {width:100%;border-collapse:collapse;table-layout:fixed;}
.docs th,.docs td {padding:.4rem;text-align:left;border-bottom:1px solid #ddd;overflow-wrap:anywhere;vertical-align:top;}
.docs th {position:sticky;top:0;background:#f3f3f3;}
.docs .bad,.bad {color:#b00020;}
.dock {position:fixed;left:1rem;right:1rem;bottom:1rem;height:14rem;}
.ledgers {height:10rem;overflow:auto;border:1px solid #d0d0d0;padding:.5rem 2rem;}
.ledgers li {display:flex;justify-content:space-between;}
.stButton {position:fixed;right:1rem;bottom:15rem;z-index:40;}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)

SPAIN = ZoneInfo("Europe/Madrid")
MAX_ATTEMPTS = 4


def clock(value):
    """ISO 8601 timestamp -> HH:MM:SS in Spain. Naive values are read as UTC. Unreadable values show a dash."""
    try:
        moment = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(SPAIN).strftime("%H:%M:%S %Z")
    except (TypeError, ValueError):
        return "—"


def now():
    return datetime.now(SPAIN).strftime("%H:%M:%S %Z")


def safe_link(url):
    return isinstance(url, str) and urlsplit(url).scheme in ("http", "https")


def table(docs, count, bad=False):
    """One row per document. docs: dicts with name, start, finish, path, url, error; updated in place."""
    out = ""
    for d in docs:
        if d.get("error"):
            finish = '<span class="bad">Failed</span>'
            path = f'<span class="bad">{escape(d["error"])}</span>'
        elif d.get("finish"):
            finish = f'<span class="ok">{escape(d["finish"])}</span>'
            path = escape(d["path"]) if d.get("path") else "—"
        else:
            finish = path = '<span class="busy">&hellip;</span>'
        url = d.get("url")
        link = (f'<a href="{escape(url)}">{escape(url)}</a>' if safe_link(url) else escape(url) if url else "—")
        out += (f'<tr><td>{escape(d["name"])}</td><td class="t">{escape(d["start"])}</td>'
                f'<td class="t">{finish}</td><td class="n">{path}</td><td class="l">{link}</td></tr>')
    head = ("<colgroup><col style='width:22%'><col style='width:9%'><col style='width:9%'>"
            "<col style='width:24%'><col style='width:36%'></colgroup>"
            "<tr><th>Filename</th><th>Start</th><th>Finish</th><th>DocuSign path</th><th>Link</th></tr>")
    return (f'<div class="stage"><div class="stage-in">'
            f'<div class="hdr">Documents<span class="{"bad" if bad else ""}">{escape(count)}</span></div>'
            f'<div class="wrap"><table class="docs">{head}{out}</table></div></div></div>')


def ledgers(items):
    """Separate list of uploaded page ledgers. items: (name, upload time)."""
    out = "".join(f'<li><span>{escape(n)} <span class="ok">&#10003;</span></span><small>uploaded {escape(t)}</small></li>'
                  for n, t in reversed(items))
    out = out or '<li class="empty">No reports uploaded yet</li>'
    return (f'<div class="dock"><div class="dock-in"><div class="hdr">Reports<span>{len(items)} uploaded</span></div>'
            f'<ul class="ledgers">{out}</ul></div></div>')


@st.cache_resource
def browser_session():
    return BrowserSession()


def configured_zone():
    try:
        return configured_zones()[0], None
    except ValueError as exc:
        return None, str(exc)


ss = st.session_state
ss.setdefault("signed_in", False)
ss.setdefault("docs", [])         # document table rows, in start order
ss.setdefault("reports", [])      # (name, time) of uploaded ledgers
ss.setdefault("notice", "")       # last run status or error, shown in the table header
ss.setdefault("notice_bad", False)
ss.setdefault("login_error", False)

zone, zone_error = configured_zone()
button = st.empty()  # one fixed spot (see .stButton); emptied while work runs
view = st.empty()
ledger_view = st.empty()
SETUP_POS = "<style>:root {--bx: calc(var(--edge) + var(--fs) * .2); --by: calc(var(--fs) * 1.5);}</style>"  # first screen: viewport bottom right
HIDE = "<style>.stButton {display: none !important;}</style>"  # button must vanish at once, not when the run ends
show_table = ss.signed_in or bool(ss.docs) or bool(ss.reports) or bool(ss.notice)


def sign_in():
    ss.login_error = False
    ss.notice, ss.notice_bad = "", False
    view.markdown(table([], "Signing in"), unsafe_allow_html=True)
    try:
        outcome = browser_session().login(os.environ.get("CLM_URL", ""), progress=lambda _: None)
        result = outcome[0] if isinstance(outcome, (tuple, list)) else outcome
        if result == "signed_in":
            ss.signed_in = True
            return
        ss.notice = "Sign-in not confirmed."
    except Exception as exc:
        write_log("Sign-in failed", exception=True)
        ss.notice = redact(f"Sign-in failed: {exc}")
    ss.notice_bad = True
    ss.login_error = True


def run_zone():
    docs, reports = ss.docs, ss.reports
    docs.clear(); reports.clear()
    ss.notice, ss.notice_bad = "", False
    index = {}
    state = {"done": 0, "status": "", "issue_count": None, "failed": False}

    def count():
        return f"{state['done']} processed" + (f" · {state['status']}" if state["status"] else "")

    def paint(bad=False):
        view.markdown(table(docs, count(), bad), unsafe_allow_html=True)

    def event(item):
        kind = item.get("type") if isinstance(item, dict) else None
        if kind in ("document_failed", "ledger_uploaded"):
            write_log(f"{kind}: {item}")
        if kind == "status":
            state["status"] = str(item.get("message", ""))
        elif kind in ("document_started", "document_finished", "document_failed"):
            key = item.get("document_id") or item.get("url") or item.get("name")
            row = index.get(key)
            if row is None:  # a retry reuses its row
                row = index[key] = {"name": item.get("name") or "—"}
                docs.append(row)
            row["url"] = item.get("url")
            row["start"] = clock(item.get("started_at")) if item.get("started_at") else now()
            if kind == "document_started":
                row.update(finish=None, path=None, error=None)
            elif kind == "document_finished":
                if not row.get("finish"):
                    state["done"] += 1
                row.update(finish=clock(item.get("processed_at")), path=item.get("docusign_path"), error=None)
            else:
                state["failed"] = True
                attempts = item.get("attempts")
                reason = str(item.get("reason") or "Unknown error")
                row.update(finish=None, path=None, error=f"{reason} (attempt {attempts} of {item.get('max_attempts', MAX_ATTEMPTS)})" if attempts else reason)
        elif kind == "ledger_uploaded":
            reports.append((str(item.get("name", "—")), clock(item.get("uploaded_at"))))
            if "issue_count" in item:
                state["issue_count"] = item["issue_count"]
            ledger_view.markdown(ledgers(reports), unsafe_allow_html=True)
        paint()

    def progress(message):
        write_log(message)

    paint()
    write_log(f"Starting processing for zone {zone}")
    try:
        total = browser_session().process_filepart(progress, None, event)
        state["status"] = ""
        count_done = state["done"] if total is None else total
        completion = "Complete with issues" if state["failed"] or state["issue_count"] else "Complete"
        ss.notice = f"{count_done} processed. {completion}"
        write_log(ss.notice)
    except ValueError as exc:
        write_log("Processing stopped", exception=True)
        ss.notice, ss.notice_bad = redact(f"Stopped: {exc}"), True
    except Exception as exc:
        write_log("Processing failed", exception=True)
        ss.notice, ss.notice_bad = "Processing failed.", True
    ss.signed_in = False  # process_filepart always closes the browser session
    if not ss.notice_bad:
        ss.notice += ". Sign in again to start another run"


if not show_table:
    st.markdown(SETUP_POS, unsafe_allow_html=True)
    view.markdown(table([], ss.notice or zone_error or "Signed out", bool(ss.notice_bad or zone_error)), unsafe_allow_html=True)
    ledger_view.markdown(ledgers([]), unsafe_allow_html=True)
    if button.button("Try sign-in again" if ss.login_error else "Run setup"):
        button.empty()
        st.markdown(HIDE, unsafe_allow_html=True)
        if zone_error:
            ss.notice, ss.notice_bad, ss.login_error = zone_error, True, True
        else:
            sign_in()
        st.rerun()
    st.stop()

ledger_view.markdown(ledgers(ss.reports), unsafe_allow_html=True)
signed_out = not ss.signed_in
header = ss.notice or ("Signed out" if signed_out else "0 processed")
view.markdown(table(ss.docs, header, ss.notice_bad or signed_out), unsafe_allow_html=True)
if signed_out:
    if button.button("Sign in again"):
        button.empty()
        st.markdown(HIDE, unsafe_allow_html=True)
        ss.notice, ss.notice_bad = "", False
        ss.docs.clear(); ss.reports.clear()
        sign_in()
        st.rerun()
elif button.button(f"Process {zone}", disabled=bool(zone_error)):
    button.empty()
    st.markdown(HIDE, unsafe_allow_html=True)
    run_zone()
    st.rerun()
