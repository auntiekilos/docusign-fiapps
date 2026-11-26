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
