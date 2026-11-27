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
:root {color-scheme: light; --fg:#1d1d1f; --dim:#6e6e73; --accent:#007aff; --green:#248a3d;
  --bg: linear-gradient(180deg, #f7f7f9, #ececf0); --card: rgba(255,255,255,.78); --head: rgba(246,246,248,.86);
  --sep: rgba(60,60,67,.12); --edge-line: rgba(60,60,67,.16); --r: 12px; --pad: .95em;
  --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", system-ui, sans-serif; --fs: clamp(15px, .35vw + 13px, 19px); --dock: calc(var(--fs) * 14);
  --edge: calc((100vw - min(110em, 96vw)) / 2 + var(--fs) * 1.2); --bx: calc(var(--edge) + var(--fs)); --by: calc(var(--dock) + var(--fs) * 2);}
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  overflow: hidden !important; background: var(--bg) !important; color: var(--fg); font: var(--fs)/1.5 var(--sans); -webkit-font-smoothing: antialiased;}
.stApp p, .stApp button {font-family: var(--sans) !important;}
#MainMenu, footer, header, [data-testid="stToolbar"], [data-testid="stDecoration"] {display: none !important;}
.block-container {max-width: min(110em, 96vw) !important; margin: 0 auto; padding: 0 !important;}
[data-stale="true"] {opacity: 1 !important; transition: none !important;}
.stButton {position: fixed; right: var(--bx); bottom: var(--by); margin: 0; z-index: 40; width: auto !important;}
/* macOS default push button */
.stButton > button {min-height: 0 !important; padding: .3em 1em !important; font-size: .85rem; font-weight: 500; color: #fff !important;
  background: linear-gradient(180deg, #3b9cff, #007aff) !important; border: 0 !important; border-radius: 6px !important;
  box-shadow: 0 0 0 .5px rgba(0,60,160,.55), 0 1px 1px rgba(0,0,0,.18) !important;}
.stButton > button:hover {background: linear-gradient(180deg, #4aa5ff, #1a85ff) !important;}
.stButton > button:active {background: linear-gradient(180deg, #0a6fe0, #0062cc) !important;}
.stButton > button:focus-visible {outline: 3px solid rgba(0,122,255,.4) !important; outline-offset: 1px;}
.stButton > button p {color: #fff !important;}
/* Fixed geometry: every box has a size set by the viewport, never by its content. */
.stage {position: fixed; left: 0; right: 0; top: 0; bottom: var(--dock); box-sizing: border-box; padding: 1em 1.2em;
  display: flex; flex-direction: column; justify-content: center; align-items: center;}
.stage-in {width: min(110em, 96vw); height: 100%; display: flex; flex-direction: column; min-height: 0;}
.stage-in.setup {height: auto;}
.hdr {flex: none; display: flex; justify-content: space-between; padding: 1em var(--pad) .5em; font-weight: 600; font-size: .8em; color: var(--fg); height: 1.5em; box-sizing: content-box;}
.hdr span {color: var(--dim); font-weight: 400;}
.wrap, .ledgers, .list {background: var(--card); -webkit-backdrop-filter: blur(24px) saturate(180%); backdrop-filter: blur(24px) saturate(180%);
  border-radius: var(--r); box-shadow: 0 0 0 .5px var(--edge-line), 0 1px 3px rgba(0,0,0,.05);}
.wrap {overflow-y: auto; overflow-x: hidden;
  min-height: 0; flex: 1 1 0; display: flex; flex-direction: column-reverse; position: relative;}  /* reverse: long content follows the newest row */
.wrap > table {margin: 0 0 auto; flex: none;}  /* pinned to the top: header and rows keep their coordinates until the box overflows */
table.docs {table-layout: fixed; width: 100%; border-collapse: separate; border-spacing: 0; font-size: .85em;}
.docs th, .docs td {border: 0 !important; background-clip: padding-box; padding-left: 0; padding-right: .8em;}
.docs th:first-child, .docs td:first-child {padding-left: var(--pad);}
.docs th {position: sticky; top: 0; background: var(--head); -webkit-backdrop-filter: blur(20px); backdrop-filter: blur(20px); z-index: 1; white-space: nowrap; text-align: left; color: var(--dim); font-weight: 500; padding-top: .45em; padding-bottom: .45em; border-bottom: 1px solid var(--sep);}
.docs th:first-child {border-top-left-radius: var(--r);} .docs th:last-child {border-top-right-radius: var(--r);}
.docs td {padding-top: .35em; padding-bottom: .35em; vertical-align: top; overflow-wrap: anywhere;}
.docs td.t {white-space: nowrap; font-variant-numeric: tabular-nums;}
.docs a {color: var(--dim); text-decoration: none;}
.docs .ok {color: var(--fg);}
.docs .busy {color: var(--dim);}
/* Scrollbars (document table, ledger): dark grey thumb on a light solid track, always visible.
   Streamlit sets `* {scrollbar-width: thin; scrollbar-color: transparent transparent}` plus a hover colour; in Chromium 121+ any such standard property
   disables ::-webkit-scrollbar styling, so the standard properties are set here with !important and the pseudo-elements are not used. */
.wrap, .ledgers {--sb: #6b6b72; --sb-track: #dcdce1; scrollbar-width: auto !important; scrollbar-color: var(--sb) var(--sb-track) !important;}
.wrap:hover, .ledgers:hover {scrollbar-color: var(--sb) var(--sb-track) !important;}
.dock {position: fixed; left: 0; right: 0; bottom: 0; z-index: 50;}
.dock-in {width: min(110em, 96vw); margin: 0 auto; padding: 0 0 .8em;}
.ledgers {list-style: none; margin: 0; padding: 0 !important; height: 9em; overflow-y: auto;}
.ledgers li.empty {color: var(--dim);}
.ledgers li {margin: 0; flex-wrap: wrap; padding: .35em var(--pad); font-size: .85em; display: flex; justify-content: space-between; gap: 1em;}
.ledgers li + li {border-top: 1px solid var(--sep);}
.ledgers .ok {color: var(--green);}
.ledgers small {color: var(--dim);}
.r {display: flex; gap: 1em; padding: .35em var(--pad);}
.r .m {flex: 1; min-width: 0; display: flex; flex-direction: column;}
.r time {color: var(--dim); white-space: nowrap; font-variant-numeric: tabular-nums;}
.list {flex: none; height: calc(2.2em * var(--slots)); box-sizing: border-box; overflow-y: auto; overflow-x: hidden; display: flex; flex-direction: column-reverse;}  /* six reserved slots; rows stay put, overflow scrolls to the newest */
.list > div.in {margin: 0 0 auto; flex: none;}
.r .ok {color: var(--green);}
.r .busy {color: var(--dim);}
.bad {color: #d70015;}
.hdr span.bad {color: #d70015;}
.hdr span {min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-left: 1em;}
.docs .bad {color: #d70015;}
.ledgers .bad, .r .bad {color: #d70015;}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)

SPAIN = ZoneInfo("Europe/Madrid")
MAX_ATTEMPTS = 4
SETUP_SLOTS = 6


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


def render(rows, note, bad=False):
    """Sign-in list. rows: (text, time, state) with state ok, busy or bad."""
    marks = {"ok": "&#10003;", "busy": "&hellip;", "bad": "&#10007;"}
    out = "".join(f'<div class="r"><span class="m"><span>{escape(text)} <span class="{state}">{marks[state]}</span></span></span>'
                  f'<time>{escape(t)}</time></div>' for text, t, state in rows)
    if not rows:
        return ""  # first screen: only the button
    return (f'<div class="stage"><div class="stage-in setup"><div class="hdr">Sign in<span class="{"bad" if bad else ""}">{escape(note)}</span></div>'
            f'<div class="list" style="--slots:{SETUP_SLOTS}"><div class="in">{out}</div></div></div></div>')


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
    out = "".join(
        f'<li><span>{escape(item[0])} '
        + ('<span class="bad">Upload unconfirmed</span>' if len(item) > 2 and item[2] else '<span class="ok">&#10003;</span>')
        + f'</span><small>{"unconfirmed" if len(item) > 2 and item[2] else "uploaded"} {escape(item[1])}</small></li>'
        for item in reversed(items)
    )
    out = out or '<li class="empty">No ledgers uploaded yet</li>'
    confirmed = sum(1 for item in items if len(item) < 3 or not item[2])
    return (f'<div class="dock"><div class="dock-in"><div class="hdr">Page ledgers<span>{confirmed} uploaded</span></div>'
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
ss.setdefault("setup_rows", [])
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
    rows = ss.setup_rows = []
    ss.login_error = False

    def show(note="", bad=False):
        view.markdown(render(rows, note, bad), unsafe_allow_html=True)

    def settle(state):
        if rows and rows[-1][2] == "busy":
            rows[-1] = (rows[-1][0], rows[-1][1], state)

    def progress(message):
        settle("ok")
        rows.append((redact(str(message)), now(), "busy"))
        show()

    rows.append(("Starting sign-in", now(), "busy"))
    show()
    try:
        outcome = browser_session().login(os.environ.get("CLM_URL", ""), progress=progress)
        result = outcome[0] if isinstance(outcome, (tuple, list)) else outcome
        if result == "signed_in":
            settle("ok")
            ss.signed_in = True
            return
        settle("bad")
        rows.append(("Sign-in not confirmed. Check the configured CLM URL and the server logs.", now(), "bad"))
    except ValueError as exc:  # includes LoginError
        settle("bad")
        rows.append((redact(str(exc)), now(), "bad"))
    except Exception:
        settle("bad")
        rows.append(("Login could not be submitted. Check the server logs and browser installation.", now(), "bad"))
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
                reason = redact(str(item.get("reason") or "Unknown error"))
                row.update(finish=None, path=None, error=f"{reason} (attempt {attempts} of {item.get('max_attempts', MAX_ATTEMPTS)})" if attempts else reason)
        elif kind in ("ledger_uploaded", "ledger_unconfirmed"):
            reports.append((str(item.get("name", "—")), clock(item.get("uploaded_at")), kind == "ledger_unconfirmed"))
            if "issue_count" in item:
                state["issue_count"] = item["issue_count"]
            ledger_view.markdown(ledgers(reports), unsafe_allow_html=True)
        elif kind == "cycle_error":
            state["status"] = "Retrying after an error"
        paint()

    def progress(message):
        write_log(message)
        state["status"] = redact(str(message))
        paint()

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
    if ss.setup_rows:
        view.markdown(render(ss.setup_rows, "Not signed in" if ss.login_error else "", ss.login_error), unsafe_allow_html=True)
    elif zone_error:
        view.markdown(render([(zone_error, now(), "bad")], "Not signed in", True), unsafe_allow_html=True)
    if button.button("Try sign-in again" if ss.login_error else "Run setup"):
        button.empty()
        st.markdown(HIDE, unsafe_allow_html=True)
        if zone_error:
            ss.setup_rows, ss.login_error = [(zone_error, now(), "bad")], True
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
