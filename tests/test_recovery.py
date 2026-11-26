import json

from clm.fileparts import read_attempt
from clm.recovery import preserve_interrupted_uploads


def test_interrupted_upload_is_recorded_as_uncertain_before_marker_removed(tmp_path, monkeypatch):
    monkeypatch.setenv('CLM_DATA_DIR', str(tmp_path))
    pending = tmp_path / 'pending'
    pending.mkdir()
    (pending / '1.json').write_text(json.dumps({'document_id': '1', 'name': 'a.pdf', 'url': 'https://example.test/?Id=1'}))
    assert preserve_interrupted_uploads('South') == 1
    assert read_attempt('South', '1')['status'] == 'upload unconfirmed'
    assert not (pending / '1.json').exists()
