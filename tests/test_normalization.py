import unittest

from problem_intelligence.normalization import normalize_identifier, normalize_url


class NormalizationTests(unittest.TestCase):
    def test_identifier_is_unicode_and_case_normalized(self) -> None:
        self.assertEqual(normalize_identifier("  Example\tCOMMUNITY  "), "example community")
        self.assertEqual(normalize_identifier("ＤＡＴＥＶ"), "datev")

    def test_identifier_rejects_empty_values(self) -> None:
        with self.assertRaises(ValueError):
            normalize_identifier(" \n ")

    def test_url_removes_fragment_but_preserves_path_case_and_query(self) -> None:
        self.assertEqual(
            normalize_url("HTTPS://Example.COM/Case/Path?q=One#reply"),
            "https://example.com/Case/Path?q=One",
        )

    def test_url_requires_http_or_https(self) -> None:
        with self.assertRaises(ValueError):
            normalize_url("javascript:alert(1)")

    def test_url_drops_embedded_credentials(self) -> None:
        self.assertEqual(
            normalize_url("https://user:secret@example.com/path?q=1"),
            "https://example.com/path?q=1",
        )
        self.assertEqual(
            normalize_url("https://user@example.com/path"),
            "https://example.com/path",
        )


if __name__ == "__main__":
    unittest.main()
