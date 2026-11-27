"""Entry point for hosts that start Streamlit with main.py."""
from config import apply_config

apply_config()
import app  # noqa: E402,F401
