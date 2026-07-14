import importlib.util
import subprocess
import tempfile
from datetime import datetime
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "generate-release-notes.py"
)


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_release_notes", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseNotesGeneratorTests(SimpleTestCase):
    def setUp(self):
        self.generator = load_generator()

    def test_parse_git_log_records(self):
        output = "abc123\x1fabc123\x1fAdd login hardening\x1e"

        commits = self.generator.parse_git_log(output)

        self.assertEqual(len(commits), 1)
        self.assertEqual(commits[0].sha, "abc123")
        self.assertEqual(commits[0].short_sha, "abc123")
        self.assertEqual(commits[0].subject, "Add login hardening")

    def test_render_release_notes_groups_commits(self):
        commits = [
            self.generator.Commit("a" * 40, "aaaaaaa", "Add login throttling"),
            self.generator.Commit("b" * 40, "bbbbbbb", "Update README"),
            self.generator.Commit("c" * 40, "ccccccc", "Refactor helpers"),
        ]

        notes = self.generator.render_release_notes(
            commits,
            from_ref="v1.0.0",
            to_ref="HEAD",
            generated_at=datetime(2026, 7, 14, 12, 30, tzinfo=timezone.utc),
        )

        self.assertIn("Generated: 2026-07-14 12:30:00Z", notes)
        self.assertIn("Range: `v1.0.0..HEAD`", notes)
        self.assertIn("## Security", notes)
        self.assertIn("- Add login throttling (`aaaaaaa`)", notes)
        self.assertIn("## Documentation", notes)
        self.assertIn("- Update README (`bbbbbbb`)", notes)
        self.assertIn("## Other changes", notes)
        self.assertIn("- Refactor helpers (`ccccccc`)", notes)

    def test_collect_commits_uses_local_git_history(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="abc123\x1fabc123\x1fAdd backup script\x1e",
        )

        with patch("subprocess.run", return_value=completed) as run:
            commits = self.generator.collect_commits("v1.0.0", "HEAD")

        self.assertEqual(commits[0].subject, "Add backup script")
        run.assert_called_once()
        args = run.call_args.args[0]
        self.assertEqual(args[0], "git")
        self.assertIn("v1.0.0..HEAD", args)

    def test_main_writes_output_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "release-notes.md"
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout="abc123\x1fabc123\x1fAdd CI gate\x1e",
            )

            with (
                patch("subprocess.run", return_value=completed),
                patch(
                    "sys.argv",
                    [
                        "generate-release-notes.py",
                        "--from",
                        "v1.0.0",
                        "--to",
                        "HEAD",
                        "--output",
                        str(output_path),
                    ],
                ),
            ):
                self.generator.main()

            self.assertTrue(output_path.exists())
            self.assertIn("Add CI gate", output_path.read_text(encoding="utf-8"))
