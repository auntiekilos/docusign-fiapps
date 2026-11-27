from clm.logging_file import write_log


def test_log_records_traceback_and_redacts_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('CLM_PASSWORD', 'secret-password')
    try:
        raise RuntimeError('failed with secret-password')
    except RuntimeError:
        write_log('Processing failed', exception=True)
    text = (tmp_path / 'app.log').read_text()
    assert 'Traceback' in text and 'RuntimeError' in text
    assert 'secret-password' not in text and '[REDACTED]' in text
