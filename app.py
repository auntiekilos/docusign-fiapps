import os

import streamlit as st
from clm.browser import BrowserSession, LoginError

st.set_page_config(page_title="CLM browser")
st.title("DocuSign CLM")
st.write("Open the CLM login page using the credentials configured on the server.")

@st.cache_resource
def browser_session():
    return BrowserSession()

retry = st.button("Try sign-in again")

if "login_result" not in st.session_state or retry:
    st.session_state.login_image = None
    try:
        status = st.empty()
        status.info("Preparing sign-in...")
        try:
            result, screenshot = browser_session().login(os.environ.get("CLM_URL", ""), progress=status.info)
        finally:
            status.empty()
        st.session_state.login_image = screenshot
        st.session_state.login_result = ("success", "Signed in to DocuSign CLM.") if result == "signed_in" else ("warning", "Sign-in not confirmed. Check the configured CLM URL and the server logs.")
    except LoginError as exc:
        st.session_state.login_image = exc.screenshot
        st.session_state.login_result = ("error", str(exc))
    except ValueError as exc:
        st.session_state.login_result = ("error", str(exc))
    except Exception:
        st.session_state.login_result = ("error", "Login could not be submitted. Check the server logs and browser installation.")

level, message = st.session_state.login_result
getattr(st, level)(message)
st.caption("The headless browser session stays open across reruns and is shared by users of this app.")

@st.fragment
def document_view():
    image_area = st.empty()
    if st.session_state.get("login_image"):
        image_area.image(st.session_state.login_image, caption="Current browser view. Input fields are masked.")
    if st.session_state.login_result[0] != "success":
        return
    st.subheader("Download a document")
    with st.form("document_download"):
        folder_text = st.text_area("Folders, one per line", value="CLIENTS\nSPAIN\nUnited States of America\n793663 - & OTHER STORIES\nNDA")
        filename = st.text_input("File name", value="NDA_793663_& OTHER STORIES.docx")
        destination = st.text_input("Save folder on this machine", value="", help="Leave blank to use the server's Downloads folder.")
        download_requested = st.form_submit_button("Download")
    if download_requested:
        progress = st.empty()
        def show_image(image):
            st.session_state.login_image = image
            image_area.image(image, caption="Current browser view. Input fields are masked.")
        try:
            path = browser_session().download(folder_text.splitlines(), filename, destination or None, progress.info, show_image)
            progress.empty()
            st.success(f"Downloaded to {path}")
        except ValueError as exc:
            progress.empty()
            st.error(str(exc))


document_view()
