<img src="assets/icon.svg" width="64" height="64" alt="">

# DocuSign CLM browser

A single-operator Streamlit app that opens a visible Chromium browser for manual CLM sign-in. It uses Playwright browser automation only. The browser runs on a dedicated thread and stays open across Streamlit reruns; SSO and MFA happen in the browser desktop. The session lasts until the browser or container closes. Closing the browser and opening a URL starts a fresh session.

## Run locally

Install Docker and Docker Compose, then run:

```sh
docker compose up --build -d
```

Open http://localhost:8501, enter your CLM URL, and select **Open browser**. Open the browser desktop link in the app and sign in there. The desktop is interactive, including for SSO and MFA prompts. Stop with `docker compose down`.

## Run on a remote server

Start the same Compose service on the server. From your own computer, keep this SSH tunnel open:

```sh
ssh -N -L 8501:127.0.0.1:8501 -L 6080:127.0.0.1:6080 user@server
```

Then visit http://localhost:8501 on your computer and use the browser desktop link. Both ports bind to the server's loopback interface. The desktop and app have no application-level authentication, so do not expose either port publicly. Anyone with access to them can control the shared browser and its authenticated session. Use a trusted SSH account and a dedicated server or container.

## Design and scope

`app.py` owns the UI and `clm/browser.py` owns browser lifecycle and navigation. Future document operations can be added to the worker's command interface so all Playwright calls remain on its thread. This iteration has no document operations, batch processing, DocuSign API integration, AI, or GPU requirement. Browser data is kept in memory, not persisted across restarts. Only use URLs and accounts you trust; the app accepts arbitrary HTTP(S) URLs and is intended for a trusted operator.

A host that runs `streamlit run main.py` can start the UI using the included entry point. The Python dependencies alone do not provide the visible desktop: this app also needs the Chromium binaries, X display, VNC and noVNC services configured in the Docker image. A managed Streamlit host that only installs `requirements.txt` and starts Streamlit does not automatically run those services. Use the Compose deployment above unless the host provides an equivalent private desktop and access to it.
