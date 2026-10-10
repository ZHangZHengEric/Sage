import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import check_docs


class ContributorGuideLinks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.docs = self.root / "docs"
        source = 'print("hello")\n'
        quickstart = "```python\n" + source + "```\n"
        files = {
            "README.md": quickstart,
            "README_CN.md": quickstart,
            "sagents/v2/README.md": quickstart,
            "examples/sagents_v2_quickstart.py": source,
            "CONTRIBUTING.md": "[Setup](README.md)\n",
            "docs/_config.yml": "exclude: [archive/]\nlogo: logo.svg\n",
            "docs/logo.svg": "<svg/>\n",
        }
        for lang in ("en", "zh"):
            files[f"docs/{lang}/api/HTTP_API_REFERENCE.md"] = (
                f"---\nlang: {lang}\nref: api\n---\nRoutes\n"
            )
            files[f"docs/{lang}/ENV_VARS.md"] = (
                f"---\nlang: {lang}\nref: env\n---\n"
            )
            files[f"docs/{lang}/applications/GETTING_STARTED.md"] = (
                f"---\nlang: {lang}\nref: start\n---\n" + quickstart
            )
        for name, text in files.items():
            self.write(name, text)
        for name, value in (
            ("ROOT", self.root),
            ("DOCS", self.docs),
        ):
            self.enterContext(patch.object(check_docs, name, value))
        self.enterContext(patch.object(check_docs, "translation_errors", return_value=[]))
        self.enterContext(patch.object(check_docs, "route_table", return_value="Routes"))
        self.enterContext(patch.object(check_docs, "server_environment", return_value={}))

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def test_valid_guide_link_without_quickstart_passes(self):
        with redirect_stdout(io.StringIO()) as output:
            check_docs.main()
        self.assertIn("5 quick-start copies", output.getvalue())

    def test_missing_local_guide_link_is_reported(self):
        self.write("CONTRIBUTING.md", "[Setup](missing-setup.md)\n")
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        self.assertEqual(str(raised.exception), "CONTRIBUTING.md: missing link missing-setup.md")

    def test_missing_repository_file_guide_link_is_reported(self):
        self.write("CONTRIBUTING.md", f"[Setup]({check_docs.REPO_URL}missing-setup.md)\n")
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        self.assertIn("CONTRIBUTING.md: missing link", str(raised.exception))
        self.assertIn("missing-setup.md", str(raised.exception))

    def test_readme_quickstart_drift_is_still_reported(self):
        self.write("README.md", "[Guide](CONTRIBUTING.md)\n")
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        self.assertIn("README.md: quick-start copy differs", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
