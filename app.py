import os

import streamlit as st
from clm.browser import BrowserSession

st.set_page_config(page_title="CLM browser")
st.title("DocuSign CLM")
st.write("Open the CLM login page using the credentials configured on the server.")

@st.cache_resource
def browser_session():
    return BrowserSession()

submitted = st.button("Sign in")

if submitted:
    try:
        with st.spinner("Submitting login..."):
            result = browser_session().login(os.environ.get("CLM_URL", ""))
        if result == "signed_in":
            st.success("Signed in to DocuSign CLM.")
        else:
            st.warning("Sign-in not confirmed. Check the configured CLM URL and the server logs.")
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("Login could not be submitted. Check the server's browser installation, login page and configured selectors.")

st.caption("The headless browser session stays open across reruns and is shared by users of this app.")
