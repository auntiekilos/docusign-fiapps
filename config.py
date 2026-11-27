"""Edit these values for each installation before building the app image."""
import os

CLM_URL = ""
CLM_USERNAME = ""
CLM_PASSWORD = ""
CLM_Zone = ""
# Docker Compose mounts persistent storage here. Change for non-Docker installs.
CLM_DATA_DIR = "/data/clm"
# Leave empty to use CLM_DATA_DIR/processed.jsonl.
CLM_HISTORY_PATH = ""


def apply_config():
    for name in ("CLM_URL", "CLM_USERNAME", "CLM_PASSWORD", "CLM_Zone", "CLM_DATA_DIR"):
        os.environ[name] = globals()[name]
    if CLM_HISTORY_PATH:
        os.environ["CLM_HISTORY_PATH"] = CLM_HISTORY_PATH
    else:
        os.environ.pop("CLM_HISTORY_PATH", None)
