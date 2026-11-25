import unittest
from clm.documents import download_document


class DownloadValidationTests(unittest.TestCase):
    def test_rejects_empty_folders_before_browser_actions(self):
        with self.assertRaises(ValueError):
            download_document(None, ['CLIENTS', ''], 'document.docx')

    def test_rejects_filename_with_path(self):
        with self.assertRaises(ValueError):
            download_document(None, ['CLIENTS'], '../document.docx')


if __name__ == '__main__':
    unittest.main()
