from django.test import SimpleTestCase

from mgw_api.services.exceptions import ExternalCommandError


class ExternalCommandErrorTests(SimpleTestCase):
    def test_command_output_is_redacted_from_exception_message(self):
        exc = ExternalCommandError(
            ["sourmash", "scripts", "manysearch"],
            1,
            stdout="sample-id-from-stdout",
            stderr="sensitive stderr with /data/media/user_7/sample.sig",
        )

        message = str(exc)

        self.assertIn("Command failed with exit code 1", message)
        self.assertIn("executable=sourmash", message)
        self.assertIn("stderr captured", message)
        self.assertIn("content redacted", message)
        self.assertNotIn("sample-id-from-stdout", message)
        self.assertNotIn("sensitive stderr", message)
        self.assertNotIn("/data/media/user_7/sample.sig", message)
        self.assertEqual(exc.stdout, "")
        self.assertEqual(exc.stderr, "")
        self.assertEqual(exc.stdout_length, len("sample-id-from-stdout"))
        self.assertEqual(
            exc.stderr_length,
            len("sensitive stderr with /data/media/user_7/sample.sig"),
        )
