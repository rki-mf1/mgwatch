# mgw_api/views.py

from django.db.models import F
from django.http import HttpResponse, Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render, redirect
from django.contrib.auth.decorators import login_required
from django.template import loader
from django.urls import reverse
from django.views import generic
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .forms import SignupForm, LoginForm
#from .forms import UploadFileForm

#from .models import Choice, Question

from .forms import FastaForm, SettingsForm
from .models import Fasta, Signature, Settings, Result

import os
import sys
import time
import subprocess
import csv


################################################################
## account management

def user_signup(request):
    if request.method == 'POST':
        form = SignupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("mgw_api:login")
    else:
        form = SignupForm()
    return render(request, 'mgw_api/signup.html', {'form': form})

def user_login(request):
    if request.method == 'POST':
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user) 
                return redirect("mgw_api:upload_fasta")
    else:
        form = LoginForm()
    return render(request, 'mgw_api/login.html', {'form': form})

def user_logout(request):
    logout(request)
    return redirect("mgw_api:login")




################################################################
## pages

@login_required
def upload_fasta(request):
    if request.method == "POST":
        fasta_form = FastaForm(request.POST, request.FILES)
        if fasta_form.is_valid():
            try:
                uploaded_file = request.FILES["file"]
                filename = uploaded_file.name
                name = fasta_form.cleaned_data.get("name")
                if not name:
                    name = os.path.splitext(filename)[0]
                if Fasta.objects.filter(user=request.user, name=name).exists():
                    messages.error(request, "A file with this name already exists. Please choose a different name or file.")
                else:
                    uploaded_file_instance = fasta_form.save(commit=False)
                    uploaded_file_instance.user = request.user
                    uploaded_file_instance.name = name
                    uploaded_file_instance.size = uploaded_file.size
                    uploaded_file_instance.processed = False
                    uploaded_file_instance.save()
                    manage_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'manage.py')
                    subprocess.Popen([sys.executable, manage_py_path, "create_signature"])
                    messages.success(request, "File submission successful! Processing will happen in the background.")
                    return redirect('mgw_api:upload_fasta')
            except Exception as e:
                messages.error(request, f"Error: file submission failed! ... {e}")
        else:
            for field, errors in fasta_form.errors.items():
                for error in errors:
                    if "extension" in error:
                        messages.error(request, "Invalid file extension!")
                    elif "start with '>'" in error:
                        messages.error(request, "Invalid FASTA format!")
                    else:
                        messages.error(request, f"{error}")
    return render(request, "mgw_api/upload_fasta.html", {"fasta_form":FastaForm()})


@login_required
def list_signature(request):
    signature_files = Signature.objects.filter(user=request.user)
    return render(request, "mgw_api/list_signature.html", {"signature_files":signature_files})


@login_required
def delete_signature(request, pk):
    signature = get_object_or_404(Signature, pk=pk, user=request.user)
    fasta = get_object_or_404(Fasta, pk=signature.fasta.pk, user=request.user)
    if request.method == "POST":
        signature.delete()
        fasta.delete()
        return redirect("mgw_api:list_signature")
    return render(request, 'mgw_api/confirm_delete_signature.html', {'signature': signature})


@login_required
def process_signature(request, pk):
    if request.method == "POST":
        try:
            signature = get_object_or_404(Signature, pk=pk, user=request.user)
            current_settings = Settings.objects.get(user=request.user)
            signature.settings_used = current_settings.to_dict()
            signature.submitted = True
            signature.save()
            manage_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'manage.py')
            subprocess.Popen([sys.executable, manage_py_path, "create_search"])
            messages.success(request, "Signature submission successful! Processing will happen in the background.")
        except Exception as e:
            messages.error(request, f"Error signature submission failed! ... {e}")
    return redirect("mgw_api:list_signature")


@login_required
def settings(request):
    sourmash_settings, created = Settings.objects.get_or_create(user=request.user)
    if request.method == "POST":
        settings_form = SettingsForm(request.POST, instance=sourmash_settings)
        if settings_form.is_valid():
            settings_form.save()
            messages.success(request, 'Settings have been successfully saved.')
            return redirect("mgw_api:settings")
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        initial_data = {
            'kmer': sourmash_settings.kmer if sourmash_settings.kmer else [21],
            'database': sourmash_settings.database if sourmash_settings.database else ["SRA"],
            'containment': sourmash_settings.containment if sourmash_settings.containment is not None else 0.10,
            }
        settings_form = SettingsForm(instance=sourmash_settings, initial=initial_data)
    return render(request, "mgw_api/settings.html", {"settings_form": settings_form})


@login_required
def list_result(request):
    result_files = Result.objects.filter(user=request.user)
    return render(request, 'mgw_api/list_result.html', {'result_files':result_files})


@login_required
def result_table(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    table_data = []
    with open(result.csv_file.path, newline="") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            table_data.append(row)
    return render(request, 'mgw_api/result_table.html', {'result': result, 'table_data': table_data})


@login_required
def delete_result(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    if request.method == "POST":
        result.delete()
        return redirect("mgw_api:list_result")
    return render(request, 'mgw_api/confirm_delete_result.html', {'result': result})

