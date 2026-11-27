"""Write application diagnostics to the persistent data directory."""
from datetime import datetime, timezone
from pathlib import Path
import os
import sys
import traceback


def redact(text):
    text = str(text)
    for key in ('CLM_PASSWORD', 'CLM_USERNAME'):
        secret = os.environ.get(key, '')
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return text


def write_log(message, *, exception=False):
    text = str(message)
    if exception:
        text += '\n' + traceback.format_exc()
    text = redact(text)
    line = f'{datetime.now(timezone.utc).isoformat()} {text}\n'
    try:
        root = Path(os.environ.get('CLM_DATA_DIR', str(Path.home() / '.clm')))
        root.mkdir(parents=True, exist_ok=True)
        with (root / 'app.log').open('a', encoding='utf-8') as stream:
            stream.write(line)
    except OSError as exc:
        print(f'Could not write application log: {type(exc).__name__}', file=sys.stderr, flush=True)
