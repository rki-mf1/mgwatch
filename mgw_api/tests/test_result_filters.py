from unittest.mock import patch

import pandas as pd
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from mgw_api.models import FilterSetting
from mgw_api.models import Result
from mgw_api.models import Signature
from mgw_api.services.filters import apply_filter_spec
from mgw_api.services.filters import build_filter_spec_from_post
from mgw_api.services.filters import merge_filter_spec_from_post
from mgw_api.services.filters import remove_filter_from_spec
from mgw_api.services.maintenance import compare_results
from mgw_api.services.maintenance import copy_watch_filters


class ResultFilterServiceTests(TestCase):
    def test_apply_filter_spec_uses_field_names_and_excludes_missing_by_default(self):
        df = pd.DataFrame(
            [
                {
                    "sra_accession": "SRR1",
                    "geo_loc_name_country_calc": "Canada",
                    "organism": "human gut metagenome",
                    "containment": 0.35,
                },
                {
                    "sra_accession": "SRR2",
                    "geo_loc_name_country_calc": "USA",
                    "organism": "wastewater metagenome",
                    "containment": 0.4,
                },
                {
                    "sra_accession": "SRR3",
                    "geo_loc_name_country_calc": "NP",
                    "organism": "human gut metagenome",
                    "containment": 0.1,
                },
            ]
        )
        filter_spec = {
            "rules": [
                {
                    "field": "geo_loc_name_country_calc",
                    "operator": "in",
                    "value": ["Canada"],
                },
                {
                    "field": "containment",
                    "operator": "range",
                    "min": "0.2",
                    "max": "",
                },
            ]
        }

        filtered = apply_filter_spec(df, filter_spec)

        self.assertEqual(filtered["sra_accession"].tolist(), ["SRR1"])

    def test_missing_field_only_matches_when_filter_allows_missing(self):
        df = pd.DataFrame([{"sra_accession": "SRR1"}])

        without_missing = apply_filter_spec(
            df,
            {
                "rules": [
                    {
                        "field": "sample_title",
                        "operator": "contains",
                        "value": "gut",
                    }
                ]
            },
        )
        with_missing = apply_filter_spec(
            df,
            {
                "rules": [
                    {
                        "field": "sample_title",
                        "operator": "contains",
                        "value": "gut",
                        "include_missing": True,
                    }
                ]
            },
        )

        self.assertTrue(without_missing.empty)
        self.assertEqual(with_missing["sra_accession"].tolist(), ["SRR1"])

    def test_build_filter_spec_from_post_normalizes_visual_controls(self):
        filter_spec = build_filter_spec_from_post(
            {
                "in__geo_loc_name_country_calc": ["Canada", "USA"],
                "contains__organism": "gut",
                "min__containment": "0.2",
                "include_missing__organism": "on",
            }
        )

        self.assertEqual(
            filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "include_missing": False,
                        "value": ["Canada", "USA"],
                    },
                    {
                        "field": "organism",
                        "operator": "contains",
                        "include_missing": True,
                        "value": "gut",
                    },
                    {
                        "field": "containment",
                        "operator": "range",
                        "include_missing": False,
                        "min": "0.2",
                        "max": "",
                    },
                ],
            },
        )

    def test_merge_filter_spec_from_post_replaces_one_field_and_keeps_others(self):
        existing_spec = {
            "rules": [
                {
                    "field": "geo_loc_name_country_calc",
                    "operator": "in",
                    "value": ["USA"],
                },
                {
                    "field": "organism",
                    "operator": "contains",
                    "value": "gut",
                },
            ]
        }

        filter_spec = merge_filter_spec_from_post(
            existing_spec,
            {
                "filter_field": "geo_loc_name_country_calc",
                "in__geo_loc_name_country_calc": ["Canada"],
            },
        )

        self.assertEqual(
            filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "organism",
                        "operator": "contains",
                        "include_missing": False,
                        "value": "gut",
                    },
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "include_missing": False,
                        "value": ["Canada"],
                    },
                ],
            },
        )

    def test_remove_filter_from_spec_removes_one_field(self):
        filter_spec = remove_filter_from_spec(
            {
                "rules": [
                    {"field": "organism", "operator": "contains", "value": "gut"},
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "value": ["Canada"],
                    },
                ]
            },
            "organism",
        )

        self.assertEqual(
            filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "include_missing": False,
                        "value": ["Canada"],
                    }
                ],
            },
        )


class ResultFilterViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="testpass123")
        self.client.login(username="owner", password="testpass123")
        self.signature = Signature.objects.create(
            user=self.user,
            name="example",
            submitted=False,
        )
        self.result = Result.objects.create(
            user=self.user,
            name="example",
            signature=self.signature,
            num_results=2,
            kmer=[21],
            database=["SRA"],
            containment=0.1,
        )
        self.result.file.save("result.csv", ContentFile(b"raw"), save=True)

    def result_metadata(self):
        return pd.DataFrame(
            [
                {
                    "sra_accession": "SRR1",
                    "containment": 0.35,
                    "geo_loc_name_country_calc": "Canada",
                    "organism": "human gut metagenome",
                    "releasedate": "2024-01-15",
                    "collection_date_sam": "2023-12-01",
                },
                {
                    "sra_accession": "SRR2",
                    "containment": 0.4,
                    "geo_loc_name_country_calc": "USA",
                    "organism": "wastewater metagenome",
                    "releasedate": "2024-03-20",
                    "collection_date_sam": "2024-02-01",
                },
            ]
        )

    def test_update_filters_adds_one_filter_to_existing_spec(self):
        FilterSetting.objects.create(
            result=self.result,
            user=self.user,
            filter_spec={
                "rules": [
                    {
                        "field": "organism",
                        "operator": "contains",
                        "value": "gut",
                    }
                ]
            },
        )

        response = self.client.post(
            reverse("mgw_api:update_filters", args=[self.result.pk]),
            {
                "filter_field": "geo_loc_name_country_calc",
                "in__geo_loc_name_country_calc": ["Canada"],
            },
        )

        self.assertEqual(response.status_code, 302)
        filter_setting = FilterSetting.objects.get(result=self.result, user=self.user)
        self.assertEqual(
            filter_setting.filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "organism",
                        "operator": "contains",
                        "include_missing": False,
                        "value": "gut",
                    },
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "include_missing": False,
                        "value": ["Canada"],
                    },
                ],
            },
        )

    def test_update_filters_removes_one_filter(self):
        FilterSetting.objects.create(
            result=self.result,
            user=self.user,
            filter_spec={
                "rules": [
                    {"field": "organism", "operator": "contains", "value": "gut"},
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "value": ["Canada"],
                    },
                ]
            },
        )

        response = self.client.post(
            reverse("mgw_api:update_filters", args=[self.result.pk]),
            {"remove_filter": "organism"},
        )

        self.assertEqual(response.status_code, 302)
        filter_setting = FilterSetting.objects.get(result=self.result, user=self.user)
        self.assertEqual(
            filter_setting.filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "include_missing": False,
                        "value": ["Canada"],
                    }
                ],
            },
        )

    def test_update_filters_saves_date_range_values(self):
        response = self.client.post(
            reverse("mgw_api:update_filters", args=[self.result.pk]),
            {
                "filter_field": "releasedate",
                "min__releasedate": "2024-01-01",
                "max__releasedate": "2024-12-31",
            },
        )

        self.assertEqual(response.status_code, 302)
        filter_setting = FilterSetting.objects.get(result=self.result, user=self.user)
        self.assertEqual(
            filter_setting.filter_spec,
            {
                "version": 1,
                "rules": [
                    {
                        "field": "releasedate",
                        "operator": "range",
                        "include_missing": False,
                        "min": "2024-01-01",
                        "max": "2024-12-31",
                    }
                ],
            },
        )

    def test_result_table_renders_compact_chips_and_single_filter_editor(self):
        FilterSetting.objects.create(
            result=self.result,
            user=self.user,
            filter_spec={
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "value": ["Canada"],
                    }
                ]
            },
        )

        with patch(
            "mgw_api.views.get_results_with_metadata",
            return_value=self.result_metadata(),
        ):
            response = self.client.get(
                reverse("mgw_api:result_table", args=[self.result.pk])
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Results shown: 1 of 2")
        self.assertContains(response, "Country: Canada")
        self.assertContains(response, 'name="remove_filter"')
        self.assertContains(response, "Choose metadata field")
        self.assertNotContains(response, 'class="filter-grid"')
        self.assertContains(response, "SRR1")
        self.assertNotContains(response, "SRR2")

    def test_result_table_renders_date_picker_inputs_for_date_filter_editor(self):
        with patch(
            "mgw_api.views.get_results_with_metadata",
            return_value=self.result_metadata(),
        ):
            response = self.client.get(
                reverse("mgw_api:result_table", args=[self.result.pk]),
                {"filter_field": "releasedate"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="min__releasedate"')
        self.assertContains(response, 'name="max__releasedate"')
        self.assertContains(response, 'class="date-filter-input"')

    def test_filtered_download_uses_saved_filter_spec(self):
        FilterSetting.objects.create(
            result=self.result,
            user=self.user,
            filter_spec={
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "value": ["Canada"],
                    }
                ]
            },
        )

        with patch(
            "mgw_api.views.get_results_with_metadata",
            return_value=self.result_metadata(),
        ):
            response = self.client.get(
                reverse("mgw_api:download_filtered_table", args=[self.result.pk])
            )

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("SRR1", content)
        self.assertNotIn("SRR2", content)


class WatchFilterTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="owner", password="testpass123")
        self.signature = Signature.objects.create(
            user=self.user,
            name="example",
            submitted=False,
        )
        self.old_result = Result.objects.create(
            user=self.user,
            name="example",
            signature=self.signature,
            num_results=2,
            is_watched=True,
        )
        self.old_result.file.save("old.csv", ContentFile(b"raw"), save=True)
        self.new_result = Result.objects.create(
            user=self.user,
            name="example",
            signature=self.signature,
            num_results=2,
        )
        self.new_result.file.save("new.csv", ContentFile(b"raw"), save=True)
        self.filter_setting = FilterSetting.objects.create(
            result=self.old_result,
            user=self.user,
            filter_spec={
                "rules": [
                    {
                        "field": "geo_loc_name_country_calc",
                        "operator": "in",
                        "value": ["Canada"],
                    }
                ]
            },
        )

    def test_copy_watch_filters_copies_filter_spec_to_new_result(self):
        copy_watch_filters(self.old_result, self.new_result)

        copied = FilterSetting.objects.get(result=self.new_result, user=self.user)
        self.assertEqual(copied.filter_spec, self.filter_setting.filter_spec)

    def test_compare_results_ignores_changes_outside_saved_watch_filter(self):
        old_metadata = pd.DataFrame(
            [
                {"sra_accession": "SRR1", "geo_loc_name_country_calc": "Canada"},
                {"sra_accession": "SRR2", "geo_loc_name_country_calc": "USA"},
            ]
        )
        new_metadata = pd.DataFrame(
            [
                {"sra_accession": "SRR1", "geo_loc_name_country_calc": "Canada"},
                {"sra_accession": "SRR3", "geo_loc_name_country_calc": "USA"},
            ]
        )

        with patch(
            "mgw_api.services.maintenance.get_results_with_metadata",
            side_effect=[old_metadata, new_metadata],
        ):
            self.assertTrue(compare_results(self.old_result, self.new_result))

    def test_compare_results_detects_changes_inside_saved_watch_filter(self):
        old_metadata = pd.DataFrame(
            [{"sra_accession": "SRR1", "geo_loc_name_country_calc": "Canada"}]
        )
        new_metadata = pd.DataFrame(
            [{"sra_accession": "SRR2", "geo_loc_name_country_calc": "Canada"}]
        )

        with patch(
            "mgw_api.services.maintenance.get_results_with_metadata",
            side_effect=[old_metadata, new_metadata],
        ):
            self.assertFalse(compare_results(self.old_result, self.new_result))
