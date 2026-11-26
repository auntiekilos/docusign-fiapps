from clm.fileparts import cleanup_expired, mark_for_deletion, RETENTION_SECONDS


def test_cleanup_retains_file_until_four_hours_after_upload(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    folder = tmp_path / 'downloads' / 'one'
    folder.mkdir(parents=True)
    (folder / 'contract.pdf').write_bytes(b'document')
    mark_for_deletion(folder, now=100)
    cleanup_expired(now=100 + RETENTION_SECONDS - 1)
    assert (folder / 'contract.pdf').read_bytes() == b'document'
    cleanup_expired(now=100 + RETENTION_SECONDS)
    assert not folder.exists()


def test_cleanup_preserves_unconfirmed_upload(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    folder = tmp_path / 'downloads' / 'pending'
    folder.mkdir(parents=True)
    (folder / 'contract.pdf').write_bytes(b'document')
    cleanup_expired(now=999999)
    assert (folder / 'contract.pdf').exists()
