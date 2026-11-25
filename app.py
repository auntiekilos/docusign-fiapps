import os

import streamlit as st
from clm.browser import BrowserSession

st.set_page_config(page_title="CLM browser")
st.title("DocuSign CLM")
st.write("Open the CLM login page using the credentials configured on the server.")

@st.cache_resource
def browser_session():
    return BrowserSession()

retry = st.button("Try sign-in again")

if "login_result" not in st.session_state or retry:
    try:
        status = st.empty()
        status.info("Preparing sign-in...")
        try:
            result = browser_session().login(os.environ.get("CLM_URL", ""), progress=status.info)
        finally:
            status.empty()
        st.session_state.login_result = ("success", "Signed in to DocuSign CLM.") if result == "signed_in" else ("warning", "Sign-in not confirmed. Check the configured CLM URL and the server logs.")
    except ValueError as exc:
        st.session_state.login_result = ("error", str(exc))
    except Exception:
        st.session_state.login_result = ("error", "Login could not be submitted. Check the server logs and browser installation.")

level, message = st.session_state.login_result
getattr(st, level)(message)

st.caption("The headless browser session stays open across reruns and is shared by users of this app.")
