import unittest

from check_translations import load_pages, translation_errors
from pathlib import Path


class TranslationChecks(unittest.TestCase):
    def setUp(self):
        self.pages = load_pages(Path(__file__).resolve().parents[1])
        self.target = "en/architecture/sagents-v2-context-budget.md"

    def test_current_docs_match(self):
        self.assertEqual(translation_errors(self.pages), [])

    def test_missing_translation_is_rejected(self):
        del self.pages[self.target]
        self.assertTrue(any("counterpart" in e for e in translation_errors(self.pages)))

    def test_navigation_order_drift_is_rejected(self):
        self.pages[self.target] = self.pages[self.target].replace(
            "nav_order: 6", "nav_order: 99"
        )
        self.assertTrue(any("nav_order" in e for e in translation_errors(self.pages)))

    def test_parent_drift_is_rejected(self):
        self.pages[self.target] = self.pages[self.target].replace(
            "parent: Architecture", "parent: API"
        )
        self.assertTrue(any("hierarchy" in e for e in translation_errors(self.pages)))

    def test_code_drift_is_rejected(self):
        self.pages[self.target] = self.pages[self.target].replace(
            "system_tokens: 16384", "system_tokens: 1"
        )
        self.assertTrue(
            any("code examples" in e for e in translation_errors(self.pages))
        )

    def test_missing_section_is_rejected(self):
        self.pages[self.target] = self.pages[self.target].replace(
            "## Configuration", "Configuration"
        )
        self.assertTrue(any("heading" in e for e in translation_errors(self.pages)))

    def test_wrong_language_link_is_rejected(self):
        target = "en/architecture/README.md"
        self.pages[target] = self.pages[target].replace(
            "(PLUGINS.md)", "(../../zh/architecture/PLUGINS.md)"
        )
        self.assertTrue(
            any("link targets" in e for e in translation_errors(self.pages))
        )


if __name__ == "__main__":
    unittest.main()
