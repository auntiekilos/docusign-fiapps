"""Preserve interrupted uploads as uncertain until an operator checks DocuSign."""
import json

from clm.fileparts import data_dir, record_failure


def interrupted_uploads():
    directory = data_dir() / 'pending'
    return sorted(directory.glob('*.json')) if directory.exists() else []


def preserve_interrupted_uploads(zone):
    """Record uncertain outcomes before removing submission markers."""
    count = 0
    for path in interrupted_uploads():
        item = json.loads(path.read_text(encoding='utf-8'))
        document_id, name, url = item['document_id'], item['name'], item['url']
        record_failure(zone, document_id, name, url,
                       'Processing stopped during upload; check the document in DocuSign.',
                       unconfirmed=True)
        path.unlink()
        count += 1
    return count
