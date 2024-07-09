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
                uploaded_file = fasta_form.save(commit=False)
                uploaded_file.user = request.user
                uploaded_file.size = request.FILES["file"].size
                uploaded_file.processed = False
                uploaded_file.save()
                manage_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'manage.py')
                subprocess.Popen([sys.executable, manage_py_path, "create_signature"])
                messages.success(request, "File submission successful! Processing will happen in the background.")
            except Exception as e:
                messages.error(request, f"Error file submission failed! ... {e}")
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
    if request.method == "POST":
        signature.delete()
        return redirect("mgw_api:list_signature")
    return render(request, 'mgw_api/confirm_delete_signature.html', {'signature': signature})


@login_required
def process_signature(request, pk):
    if request.method == "POST":
        try:
            signature = get_object_or_404(Signature, pk=pk, user=request.user)
            signature.submitted = True
            signature.save()
            manage_py_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'manage.py')
            subprocess.Popen([sys.executable, manage_py_path, "sourmash_search"])
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
            return redirect("mgw_api:settings")
    else:
        settings_form = SettingsForm(instance=sourmash_settings)
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






























################################################################
## funcitons



#class DetailView(generic.DetailView):
#    model = Question
#    template_name = "polls/detail.html"

def detail(request, question_id):
    question = get_object_or_404(Question, pk=question_id)
    return render(request, "polls/detail.html", {"question": question})

def handle_uploaded_file(f):
    with open("some/file/name.txt", "wb+") as destination:
        for chunk in f.chunks():
            destination.write(chunk)

def upload_file(request):
    if request.method == "POST":
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            handle_uploaded_file(request.FILES["file"])
            return HttpResponseRedirect("/success/url/")
    else:
        form = UploadFileForm()
    return render(request, "upload.html", {"form": form})


#class HomeView(generic.ListView):
#
#    template_name = "polls/index.html"
#    context_object_name = "latest_question_list"
#
#    def get_queryset(self):
#        """
#        Return the last five published questions (not including those set to be
#        published in the future).
#        """
#        return Question.objects.filter(pub_date__lte=timezone.now()).order_by("-pub_date")[:5]
#





#class DetailView(generic.DetailView):
#    model = Question
#    template_name = "polls/detail.html"
#
#def detail(request, question_id):
#    question = get_object_or_404(Question, pk=question_id)
#    return render(request, "polls/detail.html", {"question": question})
#
#
#
#import json
#import pandas as pd
#import io
#import gzip
#import string
#import urllib3
#from django.http import JsonResponse
#from .mongoquery import getmongo, getacc
#from django.conf import settings
#
#def home(request):
#    if request.method == 'POST':
#        form_data = json.loads(request.body.decode('utf-8'))
#        signatures = form_data['signatures']
#        mastiff_df = getacc(signatures, settings.CONFIG_DATA)
#        acc_t = tuple(mastiff_df['SRA_accession'].tolist())
#
#        meta_list = ('bioproject', 'assay_type', 'collection_date_sam', 'geo_loc_name_country_calc', 'organism', 'lat_lon')
#
#        result_list = getmongo(acc_t, meta_list, settings.CONFIG_DATA)
#        print(f"Metadata for {len(result_list)} acc returned.")
#        mastiff_dict = mastiff_df.to_dict('records')
#
#        for r in result_list:
#            for m in mastiff_dict:
#                if r['acc'] == m['SRA_accession']:
#                    r['containment'] = round(m['containment'], 2)
#                    r['cANI'] = round(m['cANI'], 2)
#                    break
#
#        return JsonResponse(result_list, safe=False)
#    return render(request, 'branchwater/index.html')
#
#def advanced(request):
#    if request.method == 'POST':
#        form_data = json.loads(request.body.decode('utf-8'))
#        signatures = form_data['signatures']
#        mastiff_df = getacc(signatures)
#        acc_t = tuple(mastiff_df['SRA_accession'].tolist())
#
#        meta_dic = form_data['metadata']
#        meta_list = tuple([key for key, value in meta_dic.items() if value])
#
#        result_list = getmongo(acc_t, meta_list, settings.CONFIG_DATA)
#        print(f"Metadata for {len(result_list)} acc returned.")
#        mastiff_dict = mastiff_df.to_dict('records')
#
#        for r in result_list:
#            for m in mastiff_dict:
#                if r['acc'] == m['SRA_accession']:
#                    r['containment'] = round(m['containment'], 2)
#                    r['cANI'] = round(m['cANI'], 2)
#                    break
#
#        return JsonResponse(result_list, safe=False)
#    return render(request, 'branchwater/advanced.html')
#
#def about(request):
#    return render(request, 'branchwater/about.html')
#
#def contact(request):
#    return render(request, 'branchwater/contact.html')
#
#def examples(request):
#    return render(request, 'branchwater//examples.html')