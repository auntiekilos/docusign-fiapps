"""Entry point for hosts that start Streamlit with main.py."""
from pathlib import Path
from runpy import run_path
from config import apply_config

apply_config()
run_path(str(Path(__file__).with_name('app.py')), run_name='__main__')
