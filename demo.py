"""Visual-only CLM demo, quiet Linux desktop look. Sample data; no network, installs or file operations."""
import time
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

import streamlit as st

st.set_page_config(page_title="CLM demo", layout="wide", initial_sidebar_state="collapsed")

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
.list {flex: none; height: calc(2.2em * var(--slots, 3)); box-sizing: border-box; overflow: hidden;}  /* one reserved slot per row, anchored from the top */
.list > div.in {margin: 0;}
.r .ok {color: var(--green);}
.r .busy {color: var(--dim);}
</style>"""
st.markdown(CSS, unsafe_allow_html=True)

SPAIN = ZoneInfo("Europe/Madrid")
ZONE, ROOT = "Zona Sur", "CLIENTS/SPAIN"
VIEW = "https://clm.example.com/atlas/Documents/View?aid=1&Id="
# Sample results pages. Real pages hold whatever the search returns.
SUBS = ["Contracts", "Orders", "Legal", "Invoices", "Correspondence", "Amendments"]
PAGES = [[(f"Example filepart {p * 9 + i + 1}.{'pdf' if i % 3 else 'docx'}", f"{p * 9 + i + 1:04d}",
           f"Example client {'ABCDEFGH'[(p + i) % 8]}/{SUBS[(p + i) % len(SUBS)]}") for i in range(9)] for p in range(7)]
DELAY = 0.3  # short, so a run shows scrolling quickly
INSTALLS = ["Streamlit", "Playwright 1.57.0", "Chromium headless shell"]


def now():
    return datetime.now(SPAIN).strftime("%H:%M:%S %Z")


def report_name(page, finish):
    """REPORT ZONA SUR N HH:MM.csv, from the last processed row's Spain time on that page."""
    return f"REPORT {ZONE.upper()} {page} {finish[:5]}.csv"


def render(title, count, rows):
    """Setup list. rows: (text, time, state)."""
    out = ""
    for text, t, state in rows:
        mark = f' <span class="{state}">{"&#10003;" if state == "ok" else "&hellip;"}</span>'
        out += f'<div class="r"><span class="m"><span>{escape(text)}{mark}</span></span><time>{escape(t)}</time></div>'
    if not rows:
        return ""  # first screen: only the button
    return (f'<div class="stage"><div class="stage-in setup"><div class="hdr">{escape(title)}<span>{escape(count)}</span></div>'
            f'<div class="list" style="--slots:{len(INSTALLS)}"><div class="in">{out}</div></div></div></div>')


def table(docs, count):
    """One row per document. docs: dicts with name, start, finish, path, link; updated in place."""
    out = ""
    for d in docs:
        done = d["finish"] is not None
        finish = f'<span class="ok">{escape(d["finish"])}</span>' if done else '<span class="busy">&hellip;</span>'
        path = escape(d["path"]) if done else '<span class="busy">&hellip;</span>'
        link = f'<a href="{escape(d["link"])}">{escape(d["link"])}</a>'
        out += (f'<tr><td>{escape(d["name"])}</td><td class="t">{escape(d["start"])}</td>'
                f'<td class="t">{finish}</td><td class="n">{path}</td><td class="l">{link}</td></tr>')
    head = ("<colgroup><col style='width:22%'><col style='width:9%'><col style='width:9%'>"
            "<col style='width:24%'><col style='width:36%'></colgroup>"
            "<tr><th>Filename</th><th>Start</th><th>Finish</th><th>DocuSign path</th><th>Link</th></tr>")
    return (f'<div class="stage"><div class="stage-in">'
            f'<div class="hdr">Documents<span>{escape(count)}</span></div>'
            f'<div class="wrap"><table class="docs">{head}{out}</table></div></div></div>')


def ledgers(items):
    """Separate list of uploaded page ledgers. items: (name, upload time)."""
    out = "".join(f'<li><span>{escape(n)} <span class="ok">&#10003;</span></span><small>uploaded {escape(t)}</small></li>'
                  for n, t in reversed(items))
    out = out or '<li class="empty">No ledgers uploaded yet</li>'
    return (f'<div class="dock"><div class="dock-in"><div class="hdr">Page ledgers<span>{len(items)} uploaded</span></div>'
            f'<ul class="ledgers">{out}</ul></div></div>')


ss = st.session_state
ss.setdefault("setup", False)
ss.setdefault("done", False)
button = st.empty()  # one fixed spot (see .stButton); emptied while work runs
view = st.empty()
ledger_view = st.empty()
SETUP_POS = "<style>:root {--bx: calc(var(--edge) + var(--fs) * .2); --by: calc(var(--fs) * 1.5);}</style>"  # first screen: viewport bottom right
HIDE = "<style>.stButton {display: none !important;}</style>"  # button must vanish at once, not when the run ends

if not ss.setup:
    st.markdown(SETUP_POS, unsafe_allow_html=True)
    if button.button("Run setup"):
        button.empty()
        st.markdown(HIDE, unsafe_allow_html=True)
        rows = []
        for name in INSTALLS:
            rows.append((f"Installing {name}", now(), "busy"))
            view.markdown(render("Setup", "Sample only", rows), unsafe_allow_html=True)
            time.sleep(0.6)
            rows[-1] = (f"Installed {name}", now(), "ok")
        view.markdown(render("Setup", "Complete", rows), unsafe_allow_html=True)
        time.sleep(0.8)
        ss.setup = True
        st.rerun()
    st.stop()

ledger_view.markdown(ledgers([]), unsafe_allow_html=True)
if ss.done:
    st.stop()
view.markdown(table([], "0 processed"), unsafe_allow_html=True)
if button.button(f"Process {ZONE}"):
    button.empty()
    st.markdown(HIDE, unsafe_allow_html=True)
    docs, reports, total = [], [], 0
    for n, page in enumerate(PAGES, 1):
        for name, doc_id, sub in page:
            link = f"{VIEW}{doc_id}"
            # Row appears when work starts; finish time and path fill in the same row.
            docs.append({"name": name, "start": now(), "finish": None, "path": f"{ROOT}/{ZONE}/{sub}", "link": link})
            view.markdown(table(docs, f"{total} processed"), unsafe_allow_html=True)
            time.sleep(DELAY)
            total += 1
            docs[-1]["finish"] = now()
            view.markdown(table(docs, f"{total} processed"), unsafe_allow_html=True)
        # Simulated upload. The ledger is listed only after it is confirmed.
        time.sleep(DELAY)
        report = report_name(n, docs[-1]["finish"])
        reports.append((report, now()))
        ledger_view.markdown(ledgers(reports), unsafe_allow_html=True)
        time.sleep(DELAY / 2)
    view.markdown(table(docs, f"{total} processed. Complete"), unsafe_allow_html=True)
    ss.done = True
