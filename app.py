import streamlit as st

from clm.browser import BrowserSession

st.set_page_config(page_title="CLM browser", page_icon="🔐")
st.title("DocuSign CLM browser")
st.write("Open your CLM URL, then sign in manually in the browser desktop.")


@st.cache_resource
def browser_session():
    return BrowserSession()


with st.form("open_url"):
    url = st.text_input("DocuSign CLM URL", placeholder="https://...")
    submitted = st.form_submit_button("Open browser")

if submitted:
    try:
        with st.spinner("Opening browser..."):
            browser_session().navigate(url)
        st.success("Browser opened. Complete sign-in in the browser desktop.")
    except Exception as exc:
        st.error(f"Could not open the URL: {exc}")

st.markdown("[Open browser desktop](http://localhost:6080/vnc.html?autoconnect=true&resize=scale)")
st.caption("For a remote server, connect through the SSH tunnel described in the README. This app uses one shared browser session.")
