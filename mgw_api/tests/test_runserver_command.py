import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase
from django.test import override_settings

from mgw_api.management.commands.runserver import Command


class RunserverCommandTests(SimpleTestCase):
    def test_initial_metadata_runs_directly_before_serving(self):
        with (
            TemporaryDirectory() as tmpdir,
            override_settings(DATA_DIR=Path(tmpdir)),
            patch.dict(os.environ, {}, clear=False),
            patch("mgw_api.services.maintenance.run_metadata") as run_metadata,
            patch(
                "mgw_api.management.commands.runserver.StaticRunServerCommand.run",
                return_value=None,
            ) as runserver,
        ):
            os.environ.pop("RUN_MAIN", None)

            Command().run()

        run_metadata.assert_called_once_with(no_download=True)
        runserver.assert_called_once_with()

    def test_initial_metadata_is_skipped_in_reloader_child(self):
        with (
            TemporaryDirectory() as tmpdir,
            override_settings(DATA_DIR=Path(tmpdir)),
            patch.dict(os.environ, {"RUN_MAIN": "true"}),
            patch("mgw_api.services.maintenance.run_metadata") as run_metadata,
            patch(
                "mgw_api.management.commands.runserver.StaticRunServerCommand.run",
                return_value=None,
            ) as runserver,
        ):
            Command().run()

        run_metadata.assert_not_called()
        runserver.assert_called_once_with()

    def test_initial_metadata_is_skipped_when_flag_exists(self):
        with (
            TemporaryDirectory() as tmpdir,
            override_settings(DATA_DIR=Path(tmpdir)),
            patch.dict(os.environ, {}, clear=False),
            patch("mgw_api.services.maintenance.run_metadata") as run_metadata,
            patch(
                "mgw_api.management.commands.runserver.StaticRunServerCommand.run",
                return_value=None,
            ) as runserver,
        ):
            os.environ.pop("RUN_MAIN", None)
            init_flag = Path(tmpdir) / "SRA" / "metadata" / "initial_setup.txt"
            init_flag.parent.mkdir(parents=True)
            init_flag.touch()

            Command().run()

        run_metadata.assert_not_called()
        runserver.assert_called_once_with()
