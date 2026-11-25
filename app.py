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
            browser_session().login(os.environ.get("CLM_URL", ""))
        st.info("Login form submitted. Authentication has not been verified.")
    except ValueError as exc:
        st.error(str(exc))
    except Exception:
        st.error("Login could not be submitted. Check the server's browser installation, login page and configured selectors.")

st.caption("The headless browser session stays open across reruns and is shared by users of this app.")
