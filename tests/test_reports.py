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
    assert first.name == 'REPORT ZONA SUR 1.csv'
    assert second.name == 'REPORT ZONA SUR 2.csv'
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
