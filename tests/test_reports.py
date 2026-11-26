import csv
import pytest
from clm.reports import create_page_report


def entry():
    return {'zone': 'Zona Sur', 'filename': 'a,b.pdf', 'docusign_path': 'CLIENTS/SPAIN/Zona Sur/A',
            'document_url': 'https://example.test/doc/1', 'document_id': '1', 'processed_at': '2026-11-26T10:00:00Z'}


def test_reports_have_csv_quoting_and_persistent_zone_sequence(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    first = create_page_report('Zona Sur', [entry()])
    second = create_page_report('Zona Sur', [entry()])
    assert first.name == 'REPORT ZONA SUR 1 11:00.csv'
    assert second.name == 'REPORT ZONA SUR 2 11:00.csv'
    with first.open(encoding='utf-8-sig', newline='') as stream:
        assert list(csv.DictReader(stream)) == [entry()]


def test_report_requires_full_path(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    item = entry()
    item['docusign_path'] = ''
    with pytest.raises(ValueError, match='complete DocuSign path'):
        create_page_report('Zona Sur', [item])


def test_report_is_uploaded_before_advancing_page(tmp_path, monkeypatch):
    from clm import fileparts, reports
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    events = []
    class Next:
        def count(self): return 1
        def is_disabled(self): return False
        def click(self):
            events.append('next')
            raise RuntimeError('stop after advancing')
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    monkeypatch.setattr(fileparts, 'select_search', lambda *a: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('a.pdf', 'https://example.test/?Id=1')])
    def process(page, name, url, zone, report, snapshot, journal):
        import json
        item = entry()
        item.update(filename=name, document_url=url, document_id='1')
        journal.write_text(json.dumps(item) + '\n')
        events.append('processed')
        return '1'
    monkeypatch.setattr(fileparts, 'process_document', process)
    monkeypatch.setattr(reports, 'upload_report', lambda *args: events.append('uploaded'))
    with pytest.raises(RuntimeError, match='stop after advancing'):
        fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set())
    assert events == ['processed', 'uploaded', 'next']


def test_total_report_includes_all_zone_history(tmp_path, monkeypatch):
    import json
    from clm.reports import create_total_report
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    one = entry()
    one['name'] = one.pop('filename')
    two = dict(one, document_id='2', zone='Zona Norte')
    (tmp_path / 'processed.jsonl').write_text(json.dumps(one) + '\n' + json.dumps(two) + '\n')
    report = create_total_report('Zona Sur')
    assert report.name == 'ZONA SUR - TOTAL LEDGER.csv'
    with report.open(encoding='utf-8-sig', newline='') as stream:
        assert [row['document_id'] for row in csv.DictReader(stream)] == ['1']
    assert create_total_report('Zona Sur') == report


def test_total_report_blocks_unfinished_uploads(tmp_path, monkeypatch):
    from clm.reports import create_total_report
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    pending = tmp_path / 'pending'
    pending.mkdir()
    (pending / '1.json').write_text('{}')
    with pytest.raises(ValueError, match='Unfinished'):
        create_total_report('Zona Sur')
    assert not (tmp_path / 'total-reports').exists()


def test_progress_events_follow_document_and_report_confirmation(tmp_path, monkeypatch):
    import json
    from clm import fileparts, reports
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    monkeypatch.setattr(fileparts, 'select_search', lambda *a: None)
    monkeypatch.setattr(fileparts, 'page_results', lambda page: [('a.pdf', 'https://example.test/?Id=1')])
    events = []
    class Next:
        def count(self): return 0
    class Page:
        url = 'https://example.test/search'
        def get_by_role(self, *args, **kwargs): return Next()
    def process(page, name, url, zone, report, snapshot, journal):
        item = entry()
        item.update(filename=name, document_url=url, document_id='1')
        journal.write_text(json.dumps(item) + '\n')
        fileparts.record_processed('1', name, zone, url, item['docusign_path'], item['processed_at'])
        return '1'
    monkeypatch.setattr(fileparts, 'process_document', process)
    monkeypatch.setattr(reports, 'upload_report', lambda *args: events.append({'type': 'upload_confirmed'}))
    assert fileparts.process_zone(Page(), lambda _: None, lambda _: None, 'Zona Sur', set(), events.append) == 1
    assert [e['type'] for e in events] == ['document_started', 'document_finished', 'upload_confirmed', 'ledger_uploaded']
    assert events[1]['docusign_path'] == 'CLIENTS/SPAIN/Zona Sur/A'
    assert events[1]['started_at'] == events[0]['started_at']


def test_total_ledger_includes_success_failure_and_uncertain_upload(tmp_path, monkeypatch):
    import json
    from clm.fileparts import record_failure, record_processed
    from clm.reports import create_total_report, total_report_issue_count

    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    record_processed('1', 'success.pdf', 'Zona Sur', 'https://example.test/1', 'CLIENTS/SPAIN/Zona Sur')
    for _ in range(4):
        record_failure('Zona Sur', '2', 'failed.pdf', 'https://example.test/2', 'Download failed')
    record_failure('Zona Sur', '3', 'uncertain.pdf', 'https://example.test/3', 'No confirmation', unconfirmed=True)
    record_failure('Zona Norte', '4', 'other.pdf', 'https://example.test/4', 'No confirmation', unconfirmed=True)
    report = create_total_report('Zona Sur')
    with report.open(encoding='utf-8-sig', newline='') as stream:
        rows = {row['document_id']: row for row in csv.DictReader(stream)}
    assert set(rows) == {'1', '2', '3'}
    assert rows['1']['status'] == 'processed'
    assert rows['2']['status'] == 'could not be processed'
    assert rows['2']['reason'] == 'Download failed' and rows['2']['attempts'] == '4'
    assert rows['3']['status'] == 'upload unconfirmed'
    assert rows['3']['reason'] == 'No confirmation'
    assert total_report_issue_count(report) == 2


def test_interrupted_page_report_reuses_same_prepared_file(tmp_path, monkeypatch):
    import json
    from clm import fileparts, reports
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    journal = tmp_path / 'page-journals' / 'zone.jsonl'
    journal.parent.mkdir()
    journal.write_text(json.dumps(entry()) + '\n')
    uploads = []
    def interrupted(page, path, report, snapshot):
        uploads.append(path)
        if len(uploads) == 1:
            raise ValueError('interrupted')
    monkeypatch.setattr(reports, 'upload_report', interrupted)
    with pytest.raises(ValueError, match='interrupted'):
        fileparts.finish_page_report(None, journal, 'Zona Sur', set(), lambda _: None, lambda _: None)
    known = set()
    fileparts.finish_page_report(None, journal, 'Zona Sur', known, lambda _: None, lambda _: None)
    assert uploads[0] == uploads[1]
    assert known == {'1'} and not journal.exists()
    assert fileparts.processed_ids() == {'1'}


@pytest.mark.parametrize('visible,should_raise', [(True, False), (False, True)])
def test_submitted_report_is_checked_without_resubmission(tmp_path, visible, should_raise):
    from clm.reports import upload_report, write_state
    target = tmp_path / 'report.csv'
    target.write_text('report')
    write_state(tmp_path / 'state.json', {'status': 'submitted', 'filename': target.name})
    class Locator:
        def is_visible(self): return False
        def wait_for(self, **kwargs): pass
        def click(self, **kwargs): pass
        def count(self): return int(visible)
        def get_by_role(self, *args, **kwargs): return self
        @property
        def first(self): return self
        def set_input_files(self, *args): raise AssertionError('Must not resubmit')
    class Page:
        def __init__(self): self.context = self
        def new_page(self): return self
        def goto(self, *args, **kwargs): pass
        def locator(self, *args, **kwargs): return Locator()
        def get_by_role(self, *args, **kwargs): return Locator()
        def close(self): pass
    search = Page()
    search.url = 'https://example.test/search?aid=1'
    if should_raise:
        with pytest.raises(ValueError, match='submitted but is not visible'):
            upload_report(search, target, lambda _: None, lambda _: None)
    else:
        upload_report(search, target, lambda _: None, lambda _: None)
