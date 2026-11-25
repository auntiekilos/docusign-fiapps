import unittest
from playwright._impl._helper import url_matches
from clm.browser import same_origin, wait_for_clm


class RedirectTests(unittest.TestCase):
    def test_playwright_predicate_receives_url_string(self):
        class Page:
            def wait_for_url(self, predicate, timeout):
                self_url = 'https://uat.example.com/atlas/Dashboard'
                if not url_matches(None, self_url, predicate):
                    raise AssertionError('CLM redirect was not accepted')
        self.assertTrue(wait_for_clm(Page(), 'https://uat.example.com/atlas/workflow'))

    def test_origin_rejects_untrusted_hosts_and_http(self):
        self.assertFalse(same_origin('https://uat.example.com.attacker.test/', 'https://uat.example.com/'))
        self.assertFalse(same_origin('http://uat.example.com/', 'https://uat.example.com/'))

    def test_non_timeout_errors_are_not_hidden(self):
        class Page:
            def wait_for_url(self, predicate, timeout):
                raise RuntimeError('unexpected error')
        with self.assertRaises(RuntimeError):
            wait_for_clm(Page(), 'https://uat.example.com/')

if __name__ == '__main__':
    unittest.main()
