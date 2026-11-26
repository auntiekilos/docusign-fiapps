# DocuSign CLM filepart processing

Set `CLM_URL`, `CLM_USERNAME`, `CLM_PASSWORD`, and `CLM_ZONES` in the environment. Set `CLM_ZONES` to a comma-separated list of folder names directly under `CLIENTS/SPAIN`, in processing order, for example `Zona Sur,Zona Norte`. Do not commit credentials. Start the app with `docker compose up --build` or `streamlit run app.py`.

The processing button searches each configured zone for `filepart`, uploads each download unchanged as a new version, traverses all search pages and repeats the search until empty. The history records document IDs, names, zones and timestamps. If an upload's outcome is uncertain, processing stops and the document must be checked before retrying.

Successful downloads are retained for four hours after confirmation. The app checks for expired files once per minute while running and on startup. If it is stopped at the deadline, deletion happens after it restarts. Docker stores downloads, pending records and history in the `clm-data` volume. Preserve that volume across restarts. `CLM_DATA_DIR` changes the storage directory outside Docker.

After processing each nonempty result page, the app creates `REPORT <ZONE> <NUMBER>.csv` and uploads it from a separate tab to `Users / Internal / Registro correcciones filepart`. The search tab stays on the results page until the report is confirmed, then advances. Reports contain the zone, filename, DocuSign path, document URL, document ID and processing time. Local journals and report files are kept in `CLM_DATA_DIR` to protect against interrupted processing; if a page or upload is unfinished, processing stops for reconciliation rather than silently repeating an upload.
