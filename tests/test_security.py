"""Security-sensitive helpers that the acceptance checker does not inspect."""

import unittest

from fastapi import HTTPException

from src.auth import hash_password, verify_password
from src.core import csv_safe, require_web_url


class SecurityTests(unittest.TestCase):
    def test_password_hash_uses_salt(self):
        first = hash_password("a-long-password")
        second = hash_password("a-long-password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("a-long-password", first))
        self.assertFalse(verify_password("wrong-password", first))

    def test_csv_formula_prefix(self):
        for value in ("=1+1", "+cmd", "-cmd", "@cmd", "  =1+1"):
            self.assertEqual(csv_safe(value), "'" + value)
        self.assertEqual(csv_safe("Ordinary title"), "Ordinary title")

    def test_untrusted_url_scheme_is_rejected(self):
        self.assertEqual(require_web_url("https://example.org/demo"), "https://example.org/demo")
        with self.assertRaises(HTTPException) as error:
            require_web_url("javascript:alert(1)")
        self.assertEqual(error.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
