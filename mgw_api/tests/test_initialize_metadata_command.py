from io import StringIO
from types import SimpleNamespace
from unittest.mock import call
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase


class InitializeMetadataCommandTests(SimpleTestCase):
    def test_initializes_missing_enabled_database_collections(self):
        databases = [
            SimpleNamespace(id="sra_metagenomes"),
            SimpleNamespace(id="other_metagenomes"),
        ]

        def collection_has_documents(database_id):
            return database_id == "sra_metagenomes"

        with (
            patch(
                "mgw_api.management.commands.initialize_metadata.enabled_databases",
                return_value=databases,
            ),
            patch(
                "mgw_api.management.commands.initialize_metadata.metadata_collection_has_documents",
                side_effect=collection_has_documents,
            ),
            patch(
                "mgw_api.management.commands.initialize_metadata.run_metadata"
            ) as run_metadata,
        ):
            output = StringIO()

            call_command("initialize_metadata", stdout=output)

        run_metadata.assert_called_once_with(
            no_download=True,
            database="other_metagenomes",
        )
        self.assertIn("Initialized metadata for: other_metagenomes", output.getvalue())
        self.assertIn(
            "Metadata already initialized for: sra_metagenomes",
            output.getvalue(),
        )

    def test_force_initializes_every_requested_database(self):
        with (
            patch(
                "mgw_api.management.commands.initialize_metadata.metadata_collection_has_documents",
                return_value=True,
            ) as collection_has_documents,
            patch(
                "mgw_api.management.commands.initialize_metadata.run_metadata"
            ) as run_metadata,
        ):
            output = StringIO()

            call_command(
                "initialize_metadata",
                "--database",
                "sra_metagenomes",
                "--database",
                "other_metagenomes",
                "--force",
                stdout=output,
            )

        collection_has_documents.assert_not_called()
        run_metadata.assert_has_calls(
            [
                call(no_download=True, database="sra_metagenomes"),
                call(no_download=True, database="other_metagenomes"),
            ]
        )
        self.assertIn(
            "Initialized metadata for: sra_metagenomes, other_metagenomes",
            output.getvalue(),
        )
