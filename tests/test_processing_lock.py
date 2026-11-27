import subprocess
import sys

import pytest

from clm.browser import BrowserSession, processing_lock


def test_processing_lock_rejects_overlap_and_releases_on_error(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    with pytest.raises(RuntimeError):
        with processing_lock():
            with pytest.raises(ValueError, match='Another run'):
                with processing_lock():
                    pass
            raise RuntimeError('interrupted')
    with processing_lock():
        pass


def test_process_holds_lock_through_final_upload_and_close(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    session = object.__new__(BrowserSession)
    operations = []

    def operation(name, *args):
        operations.append(name)
        with pytest.raises(ValueError, match='Another run'):
            with processing_lock():
                pass
        return 0 if name == 'filepart' else None

    session._operation = operation
    assert session.process_filepart() == 0
    assert operations == ['filepart', 'close']


def test_processing_lock_rejects_another_process(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    code = "from clm.browser import processing_lock\nwith processing_lock():\n    pass"
    with processing_lock():
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'Another run is using this data directory' in result.stderr
