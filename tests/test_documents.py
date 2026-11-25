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

class DownloadDirectoryTests(unittest.TestCase):
    def test_uses_hosted_files_workspace_when_writable(self):
        from unittest.mock import patch
        from pathlib import Path
        from clm.documents import default_download_directory
        with patch('clm.documents.Path.is_dir', return_value=True), patch('clm.documents.os.access', return_value=True):
            self.assertEqual(default_download_directory(), Path('/app/home/Downloads'))

    def test_falls_back_to_user_downloads(self):
        from unittest.mock import patch
        from pathlib import Path
        from clm.documents import default_download_directory
        with patch('clm.documents.Path.is_dir', return_value=False), patch('clm.documents.Path.home', return_value=Path('/test-user')):
            self.assertEqual(default_download_directory(), Path('/test-user/Downloads'))
