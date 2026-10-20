import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import check_docs
from v2_reference import server_routes


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
            "examples/v2/quickstart.py": source,
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

    def test_nested_knowledge_pages_with_valid_links_pass(self):
        self.write("knowledge/README.md", "[Guide](resources/guide.md)\n")
        self.write(
            "knowledge/resources/guide.md",
            "[Hub](../README.md)\n"
            "[Sibling](other.md#section)\n"
            f"[Repo]({check_docs.REPO_URL}README.md)\n"
            "[External](https://example.com/missing.md)\n",
        )
        self.write("knowledge/resources/other.md", "No links here.\n")
        with redirect_stdout(io.StringIO()) as output:
            check_docs.main()
        # Knowledge pages are checked for links only: they need no Jekyll front
        # matter, no Chinese counterpart and no copied quick-start example.
        self.assertIn("5 quick-start copies", output.getvalue())

    def test_missing_relative_link_in_knowledge_page_names_source_and_target(self):
        self.write("knowledge/resources/guide.md", "[Gone](../missing-page.md)\n")
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        self.assertEqual(
            str(raised.exception),
            "knowledge/resources/guide.md: missing link ../missing-page.md",
        )

    def test_missing_repository_file_link_in_knowledge_page_is_reported(self):
        self.write(
            "knowledge/resources/guide.md",
            f"[Gone]({check_docs.REPO_URL}docs/missing-file.md)\n",
        )
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        message = str(raised.exception)
        self.assertIn("knowledge/resources/guide.md: missing link", message)
        self.assertIn("docs/missing-file.md", message)

    def test_knowledge_hub_readme_links_are_checked(self):
        self.write("knowledge/README.md", "[Gone](resources/missing.md)\n")
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        self.assertEqual(
            str(raised.exception), "knowledge/README.md: missing link resources/missing.md"
        )

    def test_knowledge_links_resolve_relative_to_their_own_page(self):
        # `other.md` exists next to the README but not next to the nested guide.
        self.write("knowledge/other.md", "x\n")
        self.write("knowledge/resources/guide.md", "[Sibling](other.md)\n")
        with self.assertRaises(SystemExit) as raised:
            check_docs.main()
        self.assertIn("knowledge/resources/guide.md: missing link other.md", str(raised.exception))


class GroupedConversationRoutes(unittest.TestCase):
    def test_all_conversation_router_groups_retain_their_prefixes(self):
        routes = set(server_routes())
        expected = {
            ("POST", "/api/agent", "conversations"),
            ("GET", "/api/threads", "conversations"),
            ("POST", "/api/threads/{thread_id}/resume", "conversations"),
            ("GET", "/api/approvals", "conversations"),
            ("GET", "/api/threads/{thread_id}/download", "conversations"),
            ("POST", "/api/agents/{agent_id}/runs", "conversations"),
        }
        self.assertTrue(expected <= routes, expected - routes)


if __name__ == "__main__":
    unittest.main()
