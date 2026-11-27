import pytest
from clm import fileparts


def test_zone_configuration_requires_one_zone(monkeypatch):
    monkeypatch.delenv('CLM_Zone', raising=False)
    with pytest.raises(ValueError, match='CLM_Zone'):
        fileparts.configured_zones()
    monkeypatch.setenv('CLM_Zone', ' Zona Sur ')
    assert fileparts.configured_zones() == ['Zona Sur']
    monkeypatch.setenv('CLM_Zone', 'Zona Sur,Zona Norte')
    with pytest.raises(ValueError, match='exactly one'):
        fileparts.configured_zones()


def test_process_one_uses_configured_zone(monkeypatch):
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
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


def test_scan_restarts_browser_and_waits_when_empty(monkeypatch):
    from clm.browser import BrowserSession
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    monkeypatch.setenv('CLM_URL', 'https://example.test')
    session = object.__new__(BrowserSession)
    events = []
    counts = iter([4, 0])
    class StopTest(BaseException): pass
    def operation(name, *args):
        events.append(name)
        if name == 'filepart':
            try:
                return next(counts)
            except StopIteration:
                raise StopTest('test stop')
    def login(*args):
        events.append('login')
        return 'signed_in', None
    session._operation = operation
    session.login = login
    monkeypatch.setattr('clm.browser.time.sleep', lambda seconds: events.append(('wait', seconds)))
    with pytest.raises(StopTest, match='test stop'):
        session.process_filepart()
    assert events == ['filepart', 'close', 'login', 'filepart', 'close', ('wait', 60), 'login', 'filepart', 'close']


def test_browser_closes_when_processing_fails(monkeypatch):
    from clm.browser import BrowserSession
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    session = object.__new__(BrowserSession)
    events = []
    def operation(name, *args):
        events.append(name)
        if name == 'filepart':
            raise ValueError('interrupted')
    session._operation = operation
    class StopTest(BaseException): pass
    monkeypatch.setattr('clm.browser.time.sleep', lambda _: (_ for _ in ()).throw(StopTest()))
    with pytest.raises(StopTest):
        session.process_filepart()
    assert events == ['filepart', 'close', 'close']


def test_reappearing_processed_result_completes_without_reupload(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('example', 'https://example.test/?Id=1')])
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', {'1'}) == 0


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
        assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
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
    from clm import reports
    monkeypatch.setattr(reports, 'upload_report', lambda *args: None)
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
    assert fileparts.read_attempt('Zona Sur', '1')['status'] == 'upload unconfirmed'


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
    from clm import reports
    captured = []
    monkeypatch.setattr(reports, 'upload_report', lambda page, path, *args: captured.append(path.read_text(encoding='utf-8-sig')))
    events = []
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set(), events.append) == 0
    assert calls == [False]
    failure = next(item for item in events if item['type'] == 'document_failed')
    assert failure['attempts'] == failure['max_attempts'] == 1
    assert 'upload unconfirmed' in captured[0] and 'a.pdf' in captured[0]
    assert not (tmp_path / 'pending' / '1.json').exists()
    with create_total_report('Zona Sur').open(encoding='utf-8-sig', newline='') as stream:
        row = next(csv.DictReader(stream))
    assert row['status'] == 'upload unconfirmed'
    assert row['attempts'] == '1'
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
    assert calls == [False]


def test_confirmed_and_exhausted_results_complete_together(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [
        ('done.pdf', 'https://example.test/?Id=1'),
        ('failed.pdf', 'https://example.test/?Id=2'),
    ])
    for _ in range(fileparts.MAX_ATTEMPTS):
        fileparts.record_failure('Zona Sur', '2', 'failed.pdf', 'https://example.test/?Id=2', 'Download failed')
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', {'1'}) == 0


def test_search_filter_buttons_are_scoped_to_all_filters_dialog():
    class Locator:
        def __init__(self, scope='page'):
            self.scope = scope
        def locator(self, selector): return Locator(self.scope)
        def is_visible(self): return False
        def click(self, **kwargs): pass
        def fill(self, value): pass
        def get_by_placeholder(self, name): return Locator(self.scope)
        def get_by_text(self, name, **kwargs): return Locator(self.scope)
        def get_by_role(self, role, name=None, **kwargs):
            if role == 'button' and name in ('Location', 'File Type'):
                assert self.scope == 'All Filters'
            return Locator(name if role == 'dialog' else self.scope)
    messages = []
    fileparts.select_search(Locator(), messages.append, 'Zona Sur')
    assert messages == ['Searching for filepart documents in Zona Sur.']


def test_exhausted_path_only_failures_are_retried(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('a.pdf', 'https://example.test/?Id=1')])
    for _ in range(4):
        fileparts.record_failure('Zona Sur', '1', 'a.pdf', 'https://example.test/?Id=1', 'Could not determine the DocuSign path for a.pdf.')
    calls = []
    def process(*args):
        calls.append(True)
        raise ValueError('different failure')
    monkeypatch.setattr(fileparts, 'process_document', process)
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 0
    assert calls == [True]
    assert fileparts.read_attempt('Zona Sur', '1')['attempts'] == 1


def test_unconfirmed_document_is_reported_and_next_document_is_processed(tmp_path, monkeypatch):
    import csv
    import json
    from clm import reports
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *args: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [
        ('uncertain.pdf', 'https://example.test/?Id=1'),
        ('success.pdf', 'https://example.test/?Id=2'),
    ])
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    def process(page, name, url, zone, report, snapshot, journal):
        if name == 'uncertain.pdf':
            raise fileparts.UploadUnconfirmed('No confirmation', 'CLIENTS/SPAIN/Zona Sur/A')
        item = {'zone': zone, 'filename': name, 'docusign_path': 'CLIENTS/SPAIN/Zona Sur/B',
                'document_url': url, 'document_id': '2', 'processed_at': '2026-11-26T10:00:00Z'}
        with journal.open('a') as stream: stream.write(json.dumps(item) + '\n')
        fileparts.record_processed('2', name, zone, url, item['docusign_path'], item['processed_at'])
        return '2'
    rows = []
    def upload(page, path, *args):
        with path.open(encoding='utf-8-sig', newline='') as stream:
            rows.extend(csv.DictReader(stream))
    monkeypatch.setattr(fileparts, 'process_document', process)
    monkeypatch.setattr(reports, 'upload_report', upload)
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set()) == 1
    assert [(row['filename'], row['status']) for row in rows] == [
        ('uncertain.pdf', 'upload unconfirmed'), ('success.pdf', 'processed')]
    assert rows[0]['note'] == 'No confirmation'
    assert fileparts.processed_ids() == {'2'}
    assert fileparts.read_attempt('Zona Sur', '1')['status'] == 'upload unconfirmed'


def test_processing_cycle_retries_after_error(monkeypatch, tmp_path):
    from clm.browser import BrowserSession
    monkeypatch.setenv('CLM_Zone', 'Zona Sur')
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('CLM_URL', 'https://example.test')
    session = object.__new__(BrowserSession)
    operations, events = [], []
    class StopTest(BaseException): pass
    def operation(name, *args):
        operations.append(name)
        if name == 'filepart':
            if operations.count('filepart') == 1:
                raise ValueError('temporary error')
            raise StopTest()
    session._operation = operation
    session.login = lambda *args: ('signed_in', None)
    monkeypatch.setattr('clm.browser.time.sleep', lambda seconds: operations.append(('wait', seconds)))
    with pytest.raises(StopTest):
        session.process_filepart(event=events.append)
    assert operations == ['filepart', 'close', ('wait', 60), 'filepart', 'close']
    assert any(item['type'] == 'cycle_error' for item in events)
