from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from mgw_api.services.watch_service import compare_results
from mgw_api.services.watch_service import search_watch


class WatchServiceTests(SimpleTestCase):
    @patch("mgw_api.services.watch_service.Result.objects.get")
    @patch("mgw_api.services.watch_service.call_command")
    def test_search_watch_reads_result_pk_from_command_output(
        self, mock_call_command, mock_result_get
    ):
        expected_result = SimpleNamespace(pk=42)
        mock_result_get.return_value = expected_result

        def _write_output(*args, **kwargs):
            stdout = kwargs["stdout"]
            stdout.write("RESULT_PK: 42")

        mock_call_command.side_effect = _write_output

        result = search_watch("example", 3, 7)

        self.assertIs(result, expected_result)
        mock_result_get.assert_called_once_with(pk=42, user_id=3)

    @patch("mgw_api.services.watch_service.pd.read_csv")
    def test_compare_results_delegates_to_dataframe_equals(self, mock_read_csv):
        second_df = object()
        first_df = SimpleNamespace(equals=lambda other: other is second_df)
        mock_read_csv.side_effect = [first_df, second_df]

        left = SimpleNamespace(file=SimpleNamespace(path="left.csv"))
        right = SimpleNamespace(file=SimpleNamespace(path="right.csv"))

        self.assertTrue(compare_results(left, right))
