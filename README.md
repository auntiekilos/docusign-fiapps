# DocuSign CLM browser

A Streamlit app that starts sign-in when you open the app and submits a plain login form using headless Playwright. Use Try sign-in again to retry. The browser and its cookies remain in memory across Streamlit reruns, until the server process or browser stops. The browser is shared by everyone who can access the app. No DocuSign API, AI model or GPU is used.

## Configuration

Set `CLM_URL` to your HTTPS CLM login URL, and set `CLM_USERNAME` and `CLM_PASSWORD` as private environment secrets on the server. Do not commit them or put them in the URL. Restrict access to the Streamlit app: anyone with access can use the shared session and submit a login. The app accepts HTTPS URLs only and only enters credentials on the observed DocuSign demo login host. Use only your trusted CLM login URL.

The UAT URL redirects to `account-d.docusign.com`. The app enters the email, selects **Next**, then attempts the password and submit step on that host. The password step and headless authentication have not been verified with an account. Other login providers, SSO and MFA are not implemented. On the configured CLM origin, the app confirms sign-in only when the profile menu and Dashboard, Documents and Tasks navigation links are all visible. These indicators were observed on the signed-in UAT workflows page. If the page layout or permissions differ, the result may remain unconfirmed. Failed steps are reported without logging credentials. ChurroStack controls its own startup and dependency logs.

For ChurroStack, the app downloads the matching Chromium headless browser on first use if it is missing. The host must provide Chromium’s Linux system libraries and permit the download. Installing `requirements.txt` alone does not install Chromium. With a terminal and appropriate system permissions, run `python -m playwright install --with-deps chromium`; otherwise the platform must supply these dependencies. The app entry point is `main.py`.

For Docker, set `CLM_URL` and the two secrets in your shell and run `docker compose up --build`. Visit http://localhost:8501. Docker Compose binds the app to server loopback; use your host's authenticated access mechanism for remote use. The Playwright image includes the browser dependencies.

`clm/browser.py` owns the browser on a worker thread. Future document operations should run on that thread. Session data is not persisted across process restarts.
