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
    class Meta:
        model = Settings
        fields = ("kmer_21", "kmer_31", "kmer_51", "SRA_database")
        widgets = {
            "kmer_21":forms.CheckboxInput(attrs={"id": "checkbox"}),
            "kmer_21":forms.CheckboxInput(attrs={"id": "checkbox"}),
            "kmer_31":forms.CheckboxInput(attrs={"id": "checkbox"}),
            "SRA_database":forms.CheckboxInput(attrs={"id": "checkbox"}),
        }
