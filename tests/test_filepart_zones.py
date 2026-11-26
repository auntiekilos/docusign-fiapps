import pytest
from clm import fileparts


def test_zone_configuration_requires_one_zone(monkeypatch):
    monkeypatch.delenv('CLM_ZONES', raising=False)
    with pytest.raises(ValueError, match='CLM_ZONES'):
        fileparts.configured_zones()
    monkeypatch.setenv('CLM_ZONES', ' Zona Sur ')
    assert fileparts.configured_zones() == ['Zona Sur']
    monkeypatch.setenv('CLM_ZONES', 'Zona Sur,Zona Norte')
    with pytest.raises(ValueError, match='exactly one'):
        fileparts.configured_zones()


def test_process_one_uses_configured_zone(monkeypatch):
    monkeypatch.setenv('CLM_ZONES', 'Zona Sur')
    monkeypatch.setattr(fileparts, 'processed_ids', lambda: {'already-done'})
    calls = []
    def run_zone(page, report, snapshot, zone, known):
        calls.append((zone, known))
        return 1
    monkeypatch.setattr(fileparts, 'process_zone', run_zone)
    class Page:
        url = 'https://example.test/start'
    assert fileparts.process_one(Page(), lambda _: None, lambda _: None) == 1
    assert calls == [('Zona Sur', {'already-done'})]


def test_clean_search_restarts_browser_and_closes_after_total(monkeypatch):
    from clm.browser import BrowserSession
    monkeypatch.setenv('CLM_ZONES', 'Zona Sur')
    monkeypatch.setenv('CLM_URL', 'https://example.test')
    session = object.__new__(BrowserSession)
    events = []
    counts = iter([4, 2, 0])
    def operation(name, *args):
        events.append(name)
        return next(counts) if name == 'filepart' else None
    def login(*args):
        events.append('login')
        return 'signed_in', None
    session._operation = operation
    session.login = login
    monkeypatch.setattr('clm.browser.time.sleep', lambda seconds: events.append(('wait', seconds)))
    assert session.process_filepart() == 6
    assert events == ['filepart', ('wait', 600), 'close', 'login', 'filepart', ('wait', 600), 'close', 'login',
                      'filepart', 'total', 'close']


def test_browser_closes_when_processing_fails(monkeypatch):
    from clm.browser import BrowserSession
    monkeypatch.setenv('CLM_ZONES', 'Zona Sur')
    session = object.__new__(BrowserSession)
    events = []
    def operation(name, *args):
        events.append(name)
        if name == 'filepart':
            raise ValueError('interrupted')
    session._operation = operation
    with pytest.raises(ValueError, match='interrupted'):
        session.process_filepart()
    assert events == ['filepart', 'close']


def test_reappearing_processed_result_stops_without_reupload(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('example', 'https://example.test/?Id=1')])
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    with pytest.raises(ValueError, match='previously processed'):
        fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', {'1'})


def test_failed_document_retried_four_times_and_then_exhausted(tmp_path, monkeypatch):
    from clm.reports import create_total_report
    import csv
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('bad.pdf', 'https://example.test/?Id=1')])
    calls = []
    def fail(*args):
        calls.append(1)
        raise ValueError('Download failed')
    monkeypatch.setattr(fileparts, 'process_document', fail)
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    for _ in range(3):
        assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == -1
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
    assert len(calls) == 4
    with create_total_report('Zona Sur').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]['status'] == 'could not be processed'
    assert rows[0]['attempts'] == '4'
    assert rows[0]['document_id'] == '1'


def test_uncertain_upload_is_never_retried(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('bad.pdf', 'https://example.test/?Id=1')])
    def fail(*args):
        pending = tmp_path / 'pending'
        pending.mkdir(exist_ok=True)
        (pending / '1.json').write_text('{}')
        raise ValueError('Uncertain upload')
    monkeypatch.setattr(fileparts, 'process_document', fail)
    class Page:
        url = 'https://example.test/search'
    with pytest.raises(ValueError, match='Uncertain'):
        fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set())
    assert not fileparts.attempt_path('Zona Sur', '1').exists()


def test_unconfirmed_upload_is_not_retried_and_is_in_total_ledger(tmp_path, monkeypatch):
    import csv
    from clm.reports import create_total_report
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('a.pdf', 'https://example.test/?Id=1')])
    calls = []
    def unconfirmed(*args, **kwargs):
        calls.append(kwargs.get('retry_unconfirmed', False))
        pending = tmp_path / 'pending'
        pending.mkdir(exist_ok=True)
        (pending / '1.json').write_text('{}')
        raise fileparts.UploadUnconfirmed('Upload not confirmed')
    monkeypatch.setattr(fileparts, 'process_document', unconfirmed)
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    events = []
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set(), events.append) == 0
    assert calls == [False]
    assert events[-1]['attempts'] == events[-1]['max_attempts'] == 1
    assert not (tmp_path / 'pending' / '1.json').exists()
    with create_total_report('Zona Sur').open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['status'] == 'upload unconfirmed'
    assert row['attempts'] == '1'
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
    assert calls == [False]
