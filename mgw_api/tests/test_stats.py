import pickle
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from mgw_api.models import Fasta
from mgw_api.models import Result
from mgw_api.models import Signature
from mgw_api.models import SystemStatistic
from mgw_api.models import SystemStatisticSnapshot
from mgw_api.services.maintenance import run_download_index
from mgw_api.services.maintenance import run_index
from mgw_api.services.maintenance import run_metadata
from mgw_api.services.stats import count_index_samples
from mgw_api.services.stats import record_metadata_stats
from mgw_api.services.stats import record_search_rate
from mgw_api.services.stats import try_record_search_rate


class FakeMongoCollection:
    def count_documents(self, query):
        self.query = query
        return 42


class FakeMongoDb:
    collection = FakeMongoCollection()

    def __getitem__(self, name):
        return self.collection


class FakeMongoClient:
    closed = False
    db = FakeMongoDb()

    def __init__(self, *args, **kwargs):
        pass

    def __getitem__(self, name):
        return self.db

    def close(self):
        type(self).closed = True


class StatsServiceTests(TestCase):
    def test_count_index_samples_reads_manifest_count(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            manifest = data_dir / "SRA" / "metagenomes" / "manifest.pickle"
            manifest.parent.mkdir(parents=True)
            with open(manifest, "wb") as handle:
                pickle.dump(["SRR1", "SRR2", "SRR3"], handle, protocol=4)

            with override_settings(DATA_DIR=data_dir):
                self.assertEqual(count_index_samples(), 3)

    def test_record_metadata_stats_stores_current_and_snapshot_rows(self):
        with patch("mgw_api.services.stats.pm.MongoClient", FakeMongoClient):
            statistic = record_metadata_stats()

        self.assertEqual(
            statistic.metric,
            SystemStatistic.Metric.METADATA_SAMPLE_COUNT,
        )
        self.assertEqual(statistic.value, 42)
        self.assertTrue(FakeMongoClient.closed)
        snapshot = SystemStatisticSnapshot.objects.get(
            metric=SystemStatistic.Metric.METADATA_SAMPLE_COUNT
        )
        self.assertEqual(snapshot.value, 42)

    def test_record_search_rate_updates_running_average(self):
        user, result = self.create_result()

        record_search_rate(
            duration_seconds=2,
            index_sample_count=100,
            result=result,
            total_indexes=1,
        )
        statistic = record_search_rate(
            duration_seconds=4,
            index_sample_count=400,
            result=result,
            total_indexes=3,
        )

        self.assertEqual(statistic.observation_count, 2)
        self.assertEqual(statistic.value, 500 / 6)
        self.assertEqual(statistic.details["last_runtime_seconds"], 4)
        self.assertEqual(statistic.details["last_index_sample_count"], 400)
        self.assertEqual(statistic.details["total_runtime_seconds"], 6)
        self.assertEqual(statistic.details["total_index_sample_count"], 500)
        self.assertEqual(statistic.details["last_result_id"], result.pk)
        self.assertEqual(statistic.details["last_total_indexes"], 3)
        snapshot = SystemStatisticSnapshot.objects.filter(
            metric=SystemStatistic.Metric.AVERAGE_SEARCH_RATE_SEQUENCES_PER_SECOND
        ).latest("pk")
        self.assertEqual(snapshot.details["last_runtime_seconds"], 4)
        self.assertEqual(snapshot.details["last_index_sample_count"], 400)
        self.assertEqual(snapshot.value, 500 / 6)
        self.assertEqual(
            SystemStatisticSnapshot.objects.filter(
                metric=SystemStatistic.Metric.AVERAGE_SEARCH_RATE_SEQUENCES_PER_SECOND
            ).count(),
            2,
        )

    def test_try_record_search_rate_reads_current_index_sample_count(self):
        user, result = self.create_result()
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            manifest = data_dir / "SRA" / "metagenomes" / "manifest.pickle"
            manifest.parent.mkdir(parents=True)
            with open(manifest, "wb") as handle:
                pickle.dump(["SRR1", "SRR2", "SRR3"], handle, protocol=4)

            with override_settings(DATA_DIR=data_dir):
                statistic = try_record_search_rate(
                    duration_seconds=6,
                    databases=["SRA"],
                    result=result,
                    total_indexes=3,
                )

        self.assertEqual(statistic.value, 0.5)
        self.assertEqual(statistic.details["last_runtime_seconds"], 6)
        self.assertEqual(statistic.details["last_index_sample_count"], 3)

    def test_run_metadata_records_update_runtime(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            with (
                override_settings(DATA_DIR=data_dir),
                patch("mgw_api.services.maintenance.import_parquet"),
                patch(
                    "mgw_api.services.maintenance.monotonic",
                    side_effect=[10, 13.5],
                ),
                patch("mgw_api.services.stats.pm.MongoClient", FakeMongoClient),
            ):
                result = run_metadata(no_download=True)

        self.assertEqual(
            result,
            {"metadata_dir": str(data_dir / "SRA" / "metadata" / "parquet")},
        )
        statistic = SystemStatistic.objects.get(
            metric=SystemStatistic.Metric.METADATA_UPDATE_RUNTIME_SECONDS
        )
        self.assertEqual(statistic.value, 3.5)
        self.assertEqual(statistic.observation_count, 1)
        self.assertEqual(statistic.details["last_runtime_seconds"], 3.5)
        self.assertEqual(statistic.details["metadata_sample_count"], 42)

    def test_run_index_records_update_runtime_and_added_samples(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            metagenomes_dir = data_dir / "SRA" / "metagenomes"
            for name in [
                "updates",
                "index",
                "signatures",
                "indexing-failed",
                "manifests",
            ]:
                (metagenomes_dir / name).mkdir(parents=True, exist_ok=True)
            for accession in ["SRR1", "SRR2", "SRR3"]:
                (metagenomes_dir / "updates" / f"{accession}.sig").write_text(
                    "sig", encoding="ascii"
                )
            with open(metagenomes_dir / "manifest.pickle", "wb") as handle:
                pickle.dump([], handle, protocol=4)

            with (
                override_settings(
                    DATA_DIR=data_dir,
                    INDEX_MAX_SIGNATURES=2,
                    INDEX_MIN_ITERATOR=38,
                    DELETE_INDEXED_SIGS=False,
                ),
                patch("mgw_api.services.maintenance.update_index", return_value=0),
                patch(
                    "mgw_api.services.maintenance.monotonic",
                    side_effect=[20, 27],
                ),
            ):
                result = run_index()

        self.assertEqual(result, {"indexes_updated": 1})
        statistic = SystemStatistic.objects.get(
            metric=SystemStatistic.Metric.INDEX_UPDATE_RUNTIME_SECONDS
        )
        self.assertEqual(statistic.value, 7)
        self.assertEqual(statistic.observation_count, 1)
        self.assertEqual(statistic.details["last_runtime_seconds"], 7)
        self.assertEqual(statistic.details["samples_added"], 3)
        self.assertEqual(statistic.details["sketches_added"], 9)
        self.assertEqual(statistic.details["total_index_sample_count"], 3)

    def test_run_download_index_records_task_runtime(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)

            def fake_get_update_accessions(_updates_dir):
                return set()

            with (
                override_settings(DATA_DIR=data_dir, INDEX_MAX_SIGNATURES=2),
                patch("mgw_api.services.maintenance.run_command"),
                patch(
                    "mgw_api.services.maintenance.prepare_download_targets",
                    return_value=(
                        {"updates": data_dir / "SRA" / "metagenomes" / "updates"},
                        data_dir / "SRA" / "metagenomes" / "download_failed.pickle",
                        [],
                    ),
                ),
                patch(
                    "mgw_api.services.maintenance.get_update_accessions",
                    side_effect=fake_get_update_accessions,
                ),
                patch(
                    "mgw_api.services.maintenance.monotonic",
                    side_effect=[30, 33.25],
                ),
            ):
                result = run_download_index()

        self.assertEqual(result, {"downloaded": 0, "indexes_updated": 0})
        statistic = SystemStatistic.objects.get(
            metric=SystemStatistic.Metric.DOWNLOAD_INDEX_RUNTIME_SECONDS
        )
        self.assertEqual(statistic.value, 3.25)
        self.assertEqual(statistic.details["last_runtime_seconds"], 3.25)
        self.assertEqual(statistic.details["downloaded"], 0)
        self.assertEqual(statistic.details["indexes_updated"], 0)

    def create_result(self):
        user = User.objects.create_user(username="owner")
        fasta = Fasta.objects.create(
            user=user,
            name="query",
            size=1,
            file="user_1/query.fa",
        )
        signature = Signature.objects.create(
            user=user,
            name="query",
            fasta=fasta,
            file="user_1/query.sig",
        )
        result = Result.objects.create(
            user=user,
            name="query",
            signature=signature,
            file="",
            num_results=0,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        return user, result


class UpdateStatsCommandTests(TestCase):
    def test_update_stats_records_index_and_metadata_counts(self):
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir)
            manifest = data_dir / "SRA" / "metagenomes" / "manifest.pickle"
            manifest.parent.mkdir(parents=True)
            with open(manifest, "wb") as handle:
                pickle.dump(["SRR1", "SRR2"], handle, protocol=4)

            stdout = StringIO()
            with (
                override_settings(DATA_DIR=data_dir),
                patch("mgw_api.services.stats.pm.MongoClient", FakeMongoClient),
            ):
                call_command("update_stats", stdout=stdout)

        self.assertIn("Index samples: 2", stdout.getvalue())
        self.assertIn("Metadata samples: 42", stdout.getvalue())
        self.assertEqual(
            SystemStatistic.objects.get(
                metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT
            ).value,
            2,
        )
        self.assertEqual(
            SystemStatistic.objects.get(
                metric=SystemStatistic.Metric.METADATA_SAMPLE_COUNT
            ).value,
            42,
        )
        self.assertEqual(SystemStatisticSnapshot.objects.count(), 2)

    def test_update_stats_rejects_conflicting_scope_options(self):
        with self.assertRaisesMessage(
            CommandError,
            "--index-only and --metadata-only cannot be combined",
        ):
            call_command("update_stats", "--index-only", "--metadata-only")


class StatsViewTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="staff",
            password="testpass123",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            username="user",
            password="testpass123",
        )

    def test_staff_user_can_view_stored_stats(self):
        recorded_at = timezone.now()
        SystemStatistic.objects.create(
            metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
            value=1234,
            observation_count=0,
            recorded_at=recorded_at,
        )
        SystemStatisticSnapshot.objects.create(
            metric=SystemStatistic.Metric.INDEX_SAMPLE_COUNT,
            value=1234,
            observation_count=0,
            details={},
            recorded_at=recorded_at,
        )
        SystemStatistic.objects.create(
            metric=SystemStatistic.Metric.AVERAGE_SEARCH_RATE_SEQUENCES_PER_SECOND,
            value=12.345,
            observation_count=2,
            recorded_at=recorded_at,
        )
        SystemStatisticSnapshot.objects.create(
            metric=SystemStatistic.Metric.AVERAGE_SEARCH_RATE_SEQUENCES_PER_SECOND,
            value=12.345,
            observation_count=2,
            details={"last_runtime_seconds": 4.2},
            recorded_at=recorded_at,
        )
        SystemStatistic.objects.create(
            metric=SystemStatistic.Metric.INDEX_UPDATE_RUNTIME_SECONDS,
            value=7,
            observation_count=1,
            details={"samples_added": 3, "sketches_added": 9},
            recorded_at=recorded_at,
        )
        SystemStatisticSnapshot.objects.create(
            metric=SystemStatistic.Metric.INDEX_UPDATE_RUNTIME_SECONDS,
            value=7,
            observation_count=1,
            details={"samples_added": 3, "sketches_added": 9},
            recorded_at=recorded_at,
        )
        SystemStatistic.objects.create(
            metric=SystemStatistic.Metric.DOWNLOAD_INDEX_RUNTIME_SECONDS,
            value=8.5,
            observation_count=1,
            details={"downloaded": 4, "indexes_updated": 2},
            recorded_at=recorded_at,
        )
        SystemStatisticSnapshot.objects.create(
            metric=SystemStatistic.Metric.DOWNLOAD_INDEX_RUNTIME_SECONDS,
            value=8.5,
            observation_count=1,
            details={"downloaded": 4, "indexes_updated": 2},
            recorded_at=recorded_at,
        )
        self.client.login(username="staff", password="testpass123")

        with (
            patch("mgw_api.services.stats.count_index_samples") as count_index,
            patch("mgw_api.services.stats.count_metadata_samples") as count_metadata,
        ):
            response = self.client.get(reverse("mgw_api:stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Stats")
        self.assertContains(response, "1,234")
        self.assertContains(response, "Average search rate")
        self.assertContains(response, "12.35 seq/s")
        self.assertContains(response, "Recent activity")
        self.assertNotContains(response, "Recent snapshots")
        self.assertContains(response, "Runtime")
        self.assertContains(response, "Searches in average")
        self.assertContains(response, "N/A")
        self.assertContains(response, "4.20 s")
        self.assertContains(response, "2 searches recorded")
        self.assertContains(response, "Index update runtime")
        self.assertContains(response, "7.00 s")
        self.assertContains(response, "3 samples added, 9 sketches added")
        self.assertContains(response, "Sample download/index runtime")
        self.assertContains(response, "8.50 s")
        self.assertContains(response, "4 samples downloaded, 2 index batches")
        count_index.assert_not_called()
        count_metadata.assert_not_called()

    def test_non_staff_user_cannot_view_stats(self):
        self.client.login(username="user", password="testpass123")

        response = self.client.get(reverse("mgw_api:stats"))

        self.assertEqual(response.status_code, 403)

    def test_stats_nav_link_only_shown_to_staff_users(self):
        self.client.login(username="user", password="testpass123")
        response = self.client.get(reverse("mgw_api:upload_fasta"))
        self.assertNotContains(response, reverse("mgw_api:stats"))

        self.client.logout()
        self.client.login(username="staff", password="testpass123")
        response = self.client.get(reverse("mgw_api:upload_fasta"))
        self.assertContains(response, reverse("mgw_api:stats"))

    def test_stats_nav_link_is_shown_to_staff_on_result_table(self):
        result = self.create_result_for_user(self.staff)

        self.client.login(username="staff", password="testpass123")
        response = self.client.get(reverse("mgw_api:result_table", args=[result.pk]))

        self.assertContains(response, reverse("mgw_api:stats"))

    def test_stats_nav_link_is_hidden_from_non_staff_on_result_table(self):
        result = self.create_result_for_user(self.user)

        self.client.login(username="user", password="testpass123")
        response = self.client.get(reverse("mgw_api:result_table", args=[result.pk]))

        self.assertNotContains(response, reverse("mgw_api:stats"))

    def create_result_for_user(self, user):
        fasta = Fasta.objects.create(
            user=user,
            name="query",
            size=1,
            file=f"user_{user.pk}/query.fa",
        )
        signature = Signature.objects.create(
            user=user,
            name="query",
            fasta=fasta,
            file=f"user_{user.pk}/query.sig",
        )
        return Result.objects.create(
            user=user,
            name="query",
            signature=signature,
            file="",
            num_results=0,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
