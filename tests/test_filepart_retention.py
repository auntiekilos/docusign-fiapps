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


def test_failed_download_frees_confirmed_copies_and_retries_same_document(tmp_path, monkeypatch):
    from clm import fileparts
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    downloads = tmp_path / 'downloads'
    confirmed = downloads / 'confirmed'
    confirmed.mkdir(parents=True)
    (confirmed / 'file').write_bytes(b'uploaded')
    fileparts.mark_for_deletion(confirmed, now=0)
    uncertain = downloads / 'uncertain'
    uncertain.mkdir()
    (uncertain / 'file').write_bytes(b'uncertain')
    waits = []
    monkeypatch.setattr(fileparts.time, 'sleep', waits.append)
    class Download:
        suggested_filename = 'file.pdf'
        def __init__(self, fail): self.fail = fail
        def failure(self): return None
        def save_as(self, path):
            from pathlib import Path
            Path(path).write_bytes(b'partial' if self.fail else b'complete')
            if self.fail: raise OSError('disk full')
        def delete(self): pass
    class Expect:
        def __init__(self, download): self.value = download
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Page:
        def __init__(self): self.count = 0
        def expect_download(self, **kwargs):
            self.count += 1
            return Expect(Download(self.count == 1))
        def get_by_role(self, *args, **kwargs): return self
        def click(self): pass
    page = Page()
    folder, path = fileparts.download_for_upload(page, page, 'file.pdf', 'zone', 'id', 'https://example.test', lambda _: None)
    assert page.count == 2 and waits == [600]
    assert path.read_bytes() == b'complete'
    assert not confirmed.exists() and (uncertain / 'file').exists()
    assert sorted(p.name for p in downloads.iterdir()) == sorted(['uncertain', folder.name])


def test_download_exhaustion_is_recorded_without_fifth_attempt(tmp_path, monkeypatch):
    import pytest
    from clm import fileparts
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    waits = []
    monkeypatch.setattr(fileparts.time, 'sleep', waits.append)
    class Page:
        count = 0
        def click(self):
            self.count += 1
            raise OSError('disk full')
    page = Page()
    with pytest.raises(fileparts.DownloadFailed):
        fileparts.download_for_upload(page, page, 'file.pdf', 'zone', 'id', 'https://example.test', lambda _: None)
    assert page.count == 4 and waits == [600, 600, 600]
    assert fileparts.read_attempt('zone', 'id')['attempts'] == 4


def test_unconfirmed_upload_expires_after_two_minutes(tmp_path, monkeypatch):
    from clm.fileparts import cleanup_confirmed_downloads
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    folder = tmp_path / 'downloads' / 'uncertain'
    folder.mkdir(parents=True)
    (folder / 'file').write_bytes(b'document')
    mark_for_deletion(folder, now=100, confirmed=False)
    cleanup_confirmed_downloads()
    cleanup_expired(now=219)
    assert folder.exists()
    cleanup_expired(now=220)
    assert not folder.exists()


def test_full_disk_clears_confirmed_downloads_before_record_retry(tmp_path, monkeypatch):
    import errno
    from clm import fileparts
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    folder = tmp_path / 'downloads' / 'confirmed'
    folder.mkdir(parents=True)
    mark_for_deletion(folder, now=0)
    original = fileparts._record_failure
    calls = []
    def fail_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError(errno.ENOSPC, 'disk full')
        assert not folder.exists()
        return original(*args, **kwargs)
    monkeypatch.setattr(fileparts, '_record_failure', fail_once)
    assert fileparts.record_failure('zone', '1', 'a', 'url', 'error')['attempts'] == 1
    assert len(calls) == 2
