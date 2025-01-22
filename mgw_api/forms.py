# mgw_api/forms.py

from django import forms

from mgw_api.models import Fasta, FilterSetting, Result, Settings


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
            "file": forms.FileInput(attrs={"accept": ".fa,.fasta,.fsa,.FASTA,.fna"}),
        }


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


class SettingsForm(forms.ModelForm):
    kmer = forms.MultipleChoiceField(
        choices=[(21, "21 k-mer")],
        # We currently only have indexes for 21-mers. Hide the other k-mer
        # lengths for now.
        # choices=[(21, "21 k-mer"), (31, "31 k-mer"), (51, "51 k-mer")],
        widget=forms.CheckboxSelectMultiple,
        initial=[21],
    )
    database = forms.MultipleChoiceField(
        choices=[("SRA", "SRA database")],
        # We don't yet index any database other than SRA. Disable this for now.
        # choices=[("SRA", "SRA database"), ("RKI", "RKI database")],
        widget=forms.CheckboxSelectMultiple,
        initial=["SRA"],
    )
    containment = forms.FloatField(
        widget=forms.NumberInput(attrs={"min": 0, "max": 1, "step": 0.01}), initial=0.10
    )

    class Meta:
        model = Settings
        fields = ["kmer", "database", "containment"]


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
