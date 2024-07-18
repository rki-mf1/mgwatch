# mgw_api/forms.py

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from mgw_api.models import Fasta, Settings


class FastaForm(forms.ModelForm):
    class Meta:
        model = Fasta
        fields = ("name", "file")
        widgets = {
            "file": forms.FileInput(attrs={"accept":".fa,.fasta,.fsa,.FASTA,.fna"})
        }
    #title = forms.CharField(max_length=50)
    #file = forms.FileField()


class SignupForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User 
        fields = ["email", "username", "password1", "password2"]

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email address is already in use.")
        return email


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)


class SettingsForm(forms.ModelForm):
    kmer = forms.MultipleChoiceField(
        choices=[(21, "21 k-mer"), (31, "31 k-mer"), (51, "51 k-mer")],
        widget=forms.CheckboxSelectMultiple,
        initial=[21]
    )
    database = forms.MultipleChoiceField(
        choices=[("SRA", "SRA database"), ("OTHER", "Other database")],
        widget=forms.CheckboxSelectMultiple,
        initial=["SRA"]
    )
    containment = forms.FloatField(
        widget=forms.NumberInput(attrs={"min": 0, "max": 1, "step": 0.01}),
        initial=0.10
    )

    class Meta:
        model = Settings
        fields = ("kmer", "database", "containment")
