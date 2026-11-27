# DocuSign CLM filepart processing

Set `CLM_URL`, `CLM_USERNAME`, `CLM_PASSWORD`, and `CLM_Zone` in the environment. Set `CLM_Zone` to exactly one folder name directly under `CLIENTS/SPAIN`, for example `Zona Sur`. Use separate installations and data directories for separate zones. Do not commit credentials. Start the app with `docker compose up --build` or `streamlit run app.py`.

The processing button searches the configured zone for `filepart` and uploads each download unchanged as a new version. This temporary test stops after at most the first 10 search-result lines, uploads one report of successful documents, and closes the browser. After submission, the app waits up to 45 seconds for confirmation. Unconfirmed uploads require reconciliation.

Successful downloads are retained for four hours after confirmation. The app checks for expired files once per minute while running and on startup. If it is stopped at the deadline, deletion happens after it restarts. Docker stores downloads, pending records and history in the `clm-data` volume. Preserve that volume across restarts. `CLM_DATA_DIR` changes the storage directory outside Docker.

After processing the selected search results, the app creates `REPORT <ZONE> <NUMBER> <HH:MM>.csv` (using the last processed document time in Spain) and uploads it from a separate tab to `Users / Internal / Registro correcciones filepart`. The search tab stays open until the report is confirmed. Reports contain the zone, filename, DocuSign path, document URL, document ID and processing time. Local journals and report files are kept in `CLM_DATA_DIR` to protect against interrupted processing.

A submitted report that is not visible in DocuSign requires reconciliation before retrying. The app and its periodic cleanup worker remain running after processing stops.

A document that fails before an upload is submitted is retried on fresh passes, up to four total attempts. After the fourth failure it is listed in the total ledger as not processed, with its attempt count and reason. An unconfirmed submission is recorded for reconciliation; an interruption during submission still stops for reconciliation. Attempt records persist in `CLM_DATA_DIR`.

The main interface starts without opening DocuSign. Select **Run setup** to sign in, then use the processing button for the configured zone. The document table updates from processing events and the separate ledger list updates after each confirmed report upload. The ten-minute wait, retries and stops are displayed as status messages. `demo.py` remains a separate sample-only interface. Processing results in the interface are held in the browser session; durable processing history, attempts and reports remain in `CLM_DATA_DIR`.

For the real-environment test, each run stops after at most 10 search-result lines in its configured zone. It uploads one report of successful documents before closing the browser. Previously processed or failed lines count toward the limit. Use a separate data directory and port for each installation. This temporary test mode does not run a clean search or upload a total ledger.
