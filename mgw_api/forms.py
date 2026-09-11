# mgw_api/forms.py

from django import forms

from mgw_api.database_config import DEFAULT_DATABASE_ID
from mgw_api.database_config import LEGACY_DATABASE_ID
from mgw_api.database_config import enabled_databases
from mgw_api.database_config import normalize_database_list
from mgw_api.models import Fasta
from mgw_api.models import FilterSetting
from mgw_api.models import Result
from mgw_api.models import Settings


class DatabaseMultipleChoiceField(forms.MultipleChoiceField):
    def valid_value(self, value):
        if value == LEGACY_DATABASE_ID:
            return True
        return super().valid_value(value)


class FastaForm(forms.ModelForm):
    class Meta:
        model = Fasta
        fields = ("name", "file")
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "Drop or rename a file here ...",
                    "style": "width: calc(100% - 0px); box-sizing: border-box; height: 40px; font-size: 16px; padding-left: 10px;",
                }
            ),
            # This list of suffixes sets a filter on the extensions shown in
            # the file picker, but the user can override this by selecting to
            # view "All files" and the file will still be accepted/uploadable
            "file": forms.FileInput(
                attrs={
                    "accept": ".fa,.fasta,.fsa,.FASTA,.fna,.fa.gz,.fasta.gz,.fsa.gz,.FASTA.gz,.fna.gz"
                }
            ),
        }


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


class SettingsForm(forms.ModelForm):
    kmer = forms.MultipleChoiceField(widget=forms.CheckboxSelectMultiple, initial=[21])
    database = DatabaseMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        initial=[DEFAULT_DATABASE_ID],
    )
    containment = forms.FloatField(
        widget=forms.NumberInput(attrs={"min": 0, "max": 1, "step": 0.01}), initial=0.10
    )

    class Meta:
        model = Settings
        fields = ["kmer", "database", "containment"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        databases = enabled_databases()
        self.fields["database"].choices = [
            (database.id, database.label) for database in databases
        ]
        kmers = sorted(
            {
                profile.kmer
                for database in databases
                for profile in database.enabled_profiles
            }
        )
        self.fields["kmer"].choices = [(kmer, f"{kmer}-mers") for kmer in kmers]
        self.single_kmer_label = None
        if len(kmers) == 1:
            self.fields["kmer"].initial = [kmers[0]]
            self.single_kmer_label = str(kmers[0])

    def clean_database(self):
        return normalize_database_list(self.cleaned_data["database"])


class WatchForm(forms.ModelForm):
    class Meta:
        model = Result
        fields = ["is_watched"]


class FilterSettingForm(forms.ModelForm):
    class Meta:
        model = FilterSetting
        fields = ["filters", "range_filters", "sort_column", "sort_reverse"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for column, value in self.instance.filters.items():
            self.fields[f"filter_{column}"] = forms.CharField(
                initial=value, required=False, label=f"{column} Filter"
            )
        for column, value in self.instance.filters.items():
            self.fields[f"filter_{column}"] = forms.CharField(
                initial=value, required=False, label=f"{column} Filter (supports regex)"
            )

        for column, range_values in self.instance.range_filters.items():
            min_val, max_val = range_values
            self.fields[f"range_min_{column}"] = forms.CharField(
                initial=min_val, required=False, label=f"{column} Min"
            )
            self.fields[f"range_max_{column}"] = forms.CharField(
                initial=max_val, required=False, label=f"{column} Max"
            )
