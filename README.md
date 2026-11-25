# DocuSign CLM browser

A Streamlit app that submits a plain login form using headless Playwright. The browser and its cookies remain in memory across Streamlit reruns, until the server process or browser stops. The browser is shared by everyone who can access the app. No DocuSign API, AI model or GPU is used.

## Configuration

Set `CLM_USERNAME` and `CLM_PASSWORD` as private environment secrets on the server. Do not commit them or put them in the URL. Restrict access to the Streamlit app: anyone with access can use the shared session and submit a login. The app accepts HTTPS URLs only and refuses to enter credentials after a cross-origin redirect. Use only your trusted CLM login URL.

The login form must have both fields on the same page. The default selectors recognize common email/username and password inputs and a submit button. If needed, set `CLM_USERNAME_SELECTOR`, `CLM_PASSWORD_SELECTOR` and `CLM_SUBMIT_SELECTOR` to CSS selectors matching your login page. No SSO or MFA flow is implemented. Submitting the form does not prove authentication succeeded; the actual CLM page must be inspected to implement a reliable success check.

For ChurroStack, the host must install the Chromium browser and its Linux system libraries in the Streamlit container. Installing `requirements.txt` alone does not install Chromium. With a terminal and appropriate system permissions, run `python -m playwright install --with-deps chromium`; otherwise the platform must supply these dependencies. The app entry point is `main.py`.

For Docker, set the two secrets in your shell and run `docker compose up --build`. Visit http://localhost:8501. Docker Compose binds the app to server loopback; use your host's authenticated access mechanism for remote use. The Playwright image includes the browser dependencies.

`clm/browser.py` owns the browser on a worker thread. Future document operations should run on that thread. Session data is not persisted across process restarts.
