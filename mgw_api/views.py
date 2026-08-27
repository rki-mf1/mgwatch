# mgw_api/views.py

import json
import logging
import os
import re
from types import SimpleNamespace

import numpy as np
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse
from django.http import Http404
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import FastaForm
from .forms import FilterSettingForm
from .forms import LoginForm
from .forms import SettingsForm
from .forms import WatchForm
from .functions import apply_compare
from .functions import apply_regex
from .functions import get_numeric_columns_pandas
from .functions import get_results_with_metadata
from .functions import is_float
from .models import Fasta
from .models import FilterSetting
from .models import Job
from .models import Result
from .models import Settings
from .models import Signature
from .tasks import submit_search_job
from .tasks import submit_signature_pipeline_job

logger = logging.getLogger(__name__)

################################################################
## account management


def user_login(request):
    if request.method == "POST":
        form = LoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"]
            password = form.cleaned_data["password"]
            user = authenticate(request, username=username, password=password)
            if user:
                login(request, user)
                return redirect("mgw_api:upload_fasta")
    else:
        form = LoginForm()
    return render(request, "mgw_api/login.html", {"form": form})


def user_logout(request):
    logout(request)
    return redirect("mgw_api:login")


################################################################
## pages


@login_required
def upload_fasta(request):
    sourmash_settings, created = Settings.objects.get_or_create(user=request.user)
    settings_form = SettingsForm(instance=sourmash_settings)
    if request.method == "POST":
        ## handle settings
        if (
            "kmer" in request.POST
            or "database" in request.POST
            or "containment" in request.POST
        ):
            settings_form = SettingsForm(request.POST, instance=sourmash_settings)
            if settings_form.is_valid():
                settings_form.save()
                return redirect(reverse("mgw_api:upload_fasta"))
            else:
                messages.error(request, "Please correct the errors below.")
        ## handle upload
        if "name" in request.POST or "file" in request.POST:
            ## handle upload fasta
            fasta_form = FastaForm(request.POST, request.FILES)
            if fasta_form.is_valid():
                try:
                    uploaded_file = request.FILES["file"]
                    filename = uploaded_file.name
                    name = fasta_form.cleaned_data.get("name")
                    if not name:
                        name = os.path.splitext(filename)[0]
                    if Fasta.objects.filter(user=request.user, name=name).exists():
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "A file with this name already exists. Please choose a different name or file.",
                            }
                        )
                    else:
                        with transaction.atomic():
                            uploaded_file_instance = fasta_form.save(commit=False)
                            uploaded_file_instance.user = request.user
                            uploaded_file_instance.name = name
                            uploaded_file_instance.size = uploaded_file.size
                            uploaded_file_instance.processed = False
                            uploaded_file_instance.status = "Queued"
                            uploaded_file_instance.save()
                            submit_signature_pipeline_job(fasta=uploaded_file_instance)
                        return JsonResponse(
                            {
                                "success": True,
                                "message": "File submission successful. Processing will happen in the background.",
                                "fasta_id": uploaded_file_instance.id,
                                "result_url": reverse(
                                    "mgw_api:search_result",
                                    kwargs={"fasta_id": uploaded_file_instance.id},
                                ),
                            }
                        )
                except Exception:
                    logger.exception(
                        "FASTA upload submission failed for user_id=%s",
                        request.user.id,
                    )
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "Error: file submission failed. Please try again later.",
                        }
                    )
            else:
                errors = fasta_form.errors.as_json()
                return JsonResponse({"success": False, "error": errors})
    else:
        fasta_form = FastaForm()
    return render(
        request,
        "mgw_api/upload_fasta.html",
        {"fasta_form": fasta_form, "settings_form": settings_form},
    )


@login_required
def check_processing_status(request, fasta_id):
    fasta = get_object_or_404(Fasta, id=fasta_id, user=request.user)
    job = (
        Job.objects.filter(fasta=fasta, user=request.user)
        .order_by("-created_at")
        .first()
    )
    if job:
        payload = {
            "status": fasta.status,
            "state": job.state,
            "message": job.status_message,
            "current": job.progress_current,
            "total": job.progress_total,
            "percent": job.progress_percent,
            "fasta_id": fasta_id,
            "result_pk": fasta.result_pk,
            "job_id": job.pk,
        }
    else:
        payload = {
            "status": fasta.status,
            "fasta_id": fasta_id,
            "result_pk": fasta.result_pk,
        }
    return JsonResponse(payload)


@login_required
def job_status(request, fasta_id):
    fasta = get_object_or_404(Fasta, id=fasta_id, user=request.user)
    job = (
        Job.objects.filter(fasta=fasta, user=request.user)
        .order_by("-created_at")
        .first()
    )
    if job and job.state in Job.ACTIVE_STATES:
        return render(
            request,
            "mgw_api/_job_status.html",
            {"fasta": fasta, "job": job},
        )
    response = HttpResponse(status=204)
    response["HX-Refresh"] = "true"
    return response


@login_required
def list_signature(request):
    signature_files = Signature.objects.filter(user=request.user)
    return render(
        request, "mgw_api/list_signature.html", {"signature_files": signature_files}
    )


@login_required
def delete_signature(request, pk):
    signature = get_object_or_404(Signature, pk=pk, user=request.user)
    fasta = get_object_or_404(Fasta, pk=signature.fasta.pk, user=request.user)
    next_url = request.GET.get("next", "mgw_api:list_result")
    if request.method == "POST":
        signature.delete()
        fasta.delete()
        return redirect("mgw_api:list_result")
    return render(
        request,
        "mgw_api/confirm_delete_signature.html",
        {"signature": signature, "next_url": next_url},
    )


@login_required
def process_signature(request, pk):
    if request.method == "POST":
        try:
            signature = get_object_or_404(Signature, pk=pk, user=request.user)
            current_settings = Settings.objects.get(user=request.user)
            with transaction.atomic():
                signature.settings_used = current_settings.to_dict()
                signature.submitted = True
                signature.save(update_fields=["settings_used", "submitted"])
                submit_search_job(signature=signature)
            messages.success(
                request,
                "Signature submission successful. Processing will happen in the background.",
            )
        except Exception:
            logger.exception(
                "Signature submission failed for signature_id=%s user_id=%s",
                pk,
                request.user.id,
            )
            messages.error(
                request,
                "Error signature submission failed. Please try again later.",
            )
    return redirect("mgw_api:list_signature")


@login_required
def sourmash_settings(request):
    sourmash_settings, created = Settings.objects.get_or_create(user=request.user)
    if request.method == "POST":
        settings_form = SettingsForm(request.POST, instance=sourmash_settings)
        if settings_form.is_valid():
            settings_form.save()
            return redirect(reverse("mgw_api:settings"))
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        initial_data = {
            "kmer": sourmash_settings.kmer if sourmash_settings.kmer else [21],
            "database": sourmash_settings.database
            if sourmash_settings.database
            else ["SRA"],
            "containment": sourmash_settings.containment
            if sourmash_settings.containment is not None
            else 0.10,
        }
        settings_form = SettingsForm(instance=sourmash_settings, initial=initial_data)
    return render(request, "mgw_api/settings.html", {"settings_form": settings_form})


@login_required
def list_watches(request):
    watches = Result.objects.filter(user=request.user, is_watched=True).order_by(
        "-date", "-time"
    )
    return render(
        request,
        "mgw_api/list_watches.html",
        {"watches": watches},
    )


@login_required
def list_result(request):
    ## handle settings
    sourmash_settings, created = Settings.objects.get_or_create(user=request.user)
    settings_form = SettingsForm(instance=sourmash_settings)
    if request.method == "POST":
        if (
            "kmer" in request.POST
            or "database" in request.POST
            or "containment" in request.POST
        ):
            settings_form = SettingsForm(request.POST, instance=sourmash_settings)
            if settings_form.is_valid():
                settings_form.save()
                return redirect(reverse("mgw_api:list_result"))
            else:
                messages.error(request, "Please correct the errors below.")
        if "signature_id" in request.POST:
            try:
                signature_id = request.POST.get("signature_id")
                signature = get_object_or_404(
                    Signature, id=signature_id, user=request.user
                )
                with transaction.atomic():
                    signature.submitted = True
                    signature.save(update_fields=["submitted"])
                    fasta = signature.fasta
                    fasta.processed = False
                    fasta.status = "Queued"
                    fasta.save(update_fields=["processed", "status"])
                    submit_search_job(signature=signature)
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Signature submission successful. Processing will happen in the background.",
                        "fasta_id": fasta.id,
                    }
                )
            except Exception:
                logger.exception(
                    "Signature search submission failed for signature_id=%s user_id=%s",
                    signature_id,
                    request.user.id,
                )
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Error: file submission failed. Please try again later.",
                    }
                )
    signatures = (
        Signature.objects.filter(user=request.user)
        .prefetch_related("result_set")
        .order_by("-date", "-time")
    )
    active_search_jobs = {}
    for job in Job.objects.filter(
        user=request.user,
        job_type=Job.JobType.SEARCH,
        state__in=Job.ACTIVE_STATES,
        signature__in=signatures,
    ).order_by("signature_id", "-created_at"):
        active_search_jobs.setdefault(job.signature_id, job)
    entries_by_name = {}
    for signature in signatures:
        entry = entries_by_name.setdefault(
            signature.name,
            SimpleNamespace(
                name=signature.name,
                signature=signature,
                fasta=signature.fasta,
                sorted_results=[],
                active_job=None,
            ),
        )
        if entry.signature is None:
            entry.signature = signature
        if entry.fasta is None:
            entry.fasta = signature.fasta
        entry.sorted_results.extend(
            signature.result_set.all().order_by("-date", "-time")
        )
        entry.sorted_results.sort(
            key=lambda result: (result.date, result.time), reverse=True
        )
        entry.active_job = active_search_jobs.get(signature.pk) or entry.active_job
    for job in (
        Job.objects.filter(
            user=request.user,
            job_type=Job.JobType.SIGNATURE_PIPELINE,
            state__in=Job.ACTIVE_STATES,
        )
        .select_related("fasta")
        .order_by("-created_at")
    ):
        if not job.fasta:
            continue
        entry = entries_by_name.setdefault(
            job.fasta.name,
            SimpleNamespace(
                name=job.fasta.name,
                signature=None,
                fasta=job.fasta,
                sorted_results=[],
                active_job=None,
            ),
        )
        if entry.active_job is None:
            entry.active_job = job
        if entry.fasta is None:
            entry.fasta = job.fasta
    sequence_entries = list(entries_by_name.values())
    sequence_entries.sort(
        key=lambda entry: (
            entry.signature.date if entry.signature else entry.fasta.upload_date
        ),
        reverse=True,
    )
    return render(
        request,
        "mgw_api/list_result.html",
        {"signatures": sequence_entries, "settings_form": settings_form},
    )


@login_required
def toggle_watch(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    if request.method == "POST":
        form = WatchForm(request.POST, instance=result)
        if form.is_valid():
            form.save()
            return JsonResponse({"status": "success"})
    return JsonResponse({"status": "fail"}, status=400)


@login_required
def result_table(request, pk):
    # handle settings
    sourmash_settings, created = Settings.objects.get_or_create(user=request.user)
    settings_form = SettingsForm(instance=sourmash_settings)

    if request.method == "POST":
        # handle settings
        if (
            "kmer" in request.POST
            or "database" in request.POST
            or "containment" in request.POST
        ):
            settings_form = SettingsForm(request.POST, instance=sourmash_settings)
            if settings_form.is_valid():
                settings_form.save()
                return redirect(reverse("mgw_api:result_table", kwargs={"pk": pk}))
            else:
                messages.error(request, "Please correct the errors below.")
    result = get_object_or_404(Result, pk=pk, user=request.user)
    context = build_result_table_context(
        request, result=result, settings_form=settings_form
    )
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return result_table_json_response(context)

    return render(request, "mgw_api/result_table.html", context)


def build_result_table_context(request, *, result, settings_form):
    watch_form = WatchForm(instance=result)
    context = {
        "result": result,
        "watch_form": watch_form,
        "settings_form": settings_form,
    }
    if result.num_results == 0:
        return context

    results_with_metadata = get_results_with_metadata(
        result, max_results=settings.MAX_SEARCH_RESULTS
    )
    # We do this mainly to convert NaT to None in order to stop a crash
    results_with_metadata = results_with_metadata.replace({np.nan: None})
    filter_settings, created = FilterSetting.objects.get_or_create(
        result=result, user=request.user
    )
    sort_column = filter_settings.sort_column
    sort_reverse = filter_settings.sort_reverse
    numeric_columns = get_numeric_columns_pandas(results_with_metadata)

    # Convert from DataFrame to lists for serialization
    headers = results_with_metadata.columns.tolist()
    rows = results_with_metadata.values.tolist()

    # FIXME: adapt filtering to pandas DataFrame
    for column, value in filter_settings.filters.items():
        rows = apply_regex(rows, column, value)
    for column, range_values in filter_settings.range_filters.items():
        for m, value in zip([1, -1], range_values):
            if value == "":
                value = None
            if is_float(value):
                rows = [row for row in rows if apply_compare(m, row, column, value)]
            elif value is not None:
                rows = apply_regex(rows, column, value)

    filter_form = FilterSettingForm(instance=filter_settings)
    context.update(
        {
            "headers": headers,
            "rows": rows,
            "filter_form": filter_form,
            "numeric_columns": numeric_columns,
            "sort_column": sort_column,
            "sort_reverse": sort_reverse,
        }
    )
    return context


def result_table_json_response(context):
    headers = context.get("headers", [])
    rows = context.get("rows", [])
    geo_loc_data = []
    lat_lon_data = []
    if headers and "geo loc name country calc" in headers and "lat lon" in headers:
        geo_loc_name_country_calc_index = headers.index("geo loc name country calc")
        lat_lon_index = headers.index("lat lon")
        geo_loc_data = [row[geo_loc_name_country_calc_index] for row in rows]
        lat_lon_data = [row[lat_lon_index] for row in rows]
    return JsonResponse(
        {
            "headers": headers,
            "rows": rows,
            "geo_loc_data": geo_loc_data,
            "lat_lon_data": lat_lon_data,
        }
    )


@login_required
def search_result(request, fasta_id):
    fasta = get_object_or_404(Fasta, pk=fasta_id, user=request.user)
    sourmash_settings, created = Settings.objects.get_or_create(user=request.user)
    settings_form = SettingsForm(instance=sourmash_settings)
    result = (
        Result.objects.filter(pk=fasta.result_pk, user=request.user).first()
        if fasta.result_pk
        else None
    )
    if result:
        context = build_result_table_context(
            request, result=result, settings_form=settings_form
        )
        if request.headers.get("HX-Request"):
            return render(request, "mgw_api/_result_table_content.html", context)
        return render(request, "mgw_api/search_result.html", context)

    job = (
        Job.objects.filter(fasta=fasta, user=request.user)
        .order_by("-created_at")
        .first()
    )
    context = {"fasta": fasta, "job": job, "result": None}
    template = (
        "mgw_api/_search_result_status.html"
        if request.headers.get("HX-Request")
        else "mgw_api/search_result.html"
    )
    return render(request, template, context)


@login_required
@require_POST
def update_filters(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    filter_settings, created = FilterSetting.objects.get_or_create(
        result=result, user=request.user
    )
    data = json.loads(request.body)
    column = data.get("column")
    min_value = data.get("min_value")
    max_value = data.get("max_value")
    value = data.get("value")
    if min_value is not None or max_value is not None:
        range_filters = filter_settings.range_filters
        range_filters[column] = [min_value, max_value]
        filter_settings.range_filters = range_filters
    elif value is not None:
        filters = filter_settings.filters
        filters[column] = value
        filter_settings.filters = filters
    filter_settings.save()
    return JsonResponse({"status": "success"})


@login_required
@require_POST
def update_sort(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    filter_settings, created = FilterSetting.objects.get_or_create(
        result=result, user=request.user
    )
    data = json.loads(request.body)
    column = data.get("column")
    if filter_settings.sort_column == int(column):
        filter_settings.sort_reverse = not filter_settings.sort_reverse
    else:
        filter_settings.sort_column = int(column)
        filter_settings.sort_reverse = False
    filter_settings.save()
    return JsonResponse({"status": "success"})


@login_required
def delete_result(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    next_url = request.GET.get("next", "mgw_api:list_result")
    if request.method == "POST":
        result.delete()
        return redirect("mgw_api:list_result")
    return render(
        request,
        "mgw_api/confirm_delete_result.html",
        {"result": result, "next_url": next_url},
    )


def _download_user_file(field_file, filename):
    if not field_file:
        raise Http404("File not found.")
    try:
        return FileResponse(
            field_file.open("rb"), as_attachment=True, filename=filename
        )
    except (FileNotFoundError, OSError) as exc:
        raise Http404("File not found.") from exc


@login_required
def download_signature_file(request, pk):
    signature = get_object_or_404(Signature, pk=pk, user=request.user)
    return _download_user_file(signature.file, os.path.basename(signature.file.name))


@login_required
def download_result_file(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    return _download_user_file(result.file, os.path.basename(result.file.name))


@login_required
def download_full_table(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    results_with_metadata = get_results_with_metadata(result)
    safe_name = re.sub("[^A-Za-z0-9]", "-", result.name)
    filename = f"{safe_name}-mgwatch-full.tsv"
    response = HttpResponse(content_type="text/tab-separated-values")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    results_with_metadata.to_csv(response, sep="\t", index=False)
    return response


# Temporarily disabled
# @login_required
# def download_filtered_table(request, pk):
#     result = get_object_or_404(Result, pk=pk, user=request.user)
#
#     results_with_metadata = get_results_with_metadata(result)
#     headers = results_with_metadata.columns.tolist()
#     rows = results_with_metadata.values.tolist()
#
#     filter_settings = get_object_or_404(FilterSetting, result=result, user=request.user)
#     for column, value in filter_settings.filters.items():
#         rows = apply_regex(rows, column, value)
#     for column, range_values in filter_settings.range_filters.items():
#         for m, value in zip([1, -1], range_values):
#             if value == "":
#                 value = None
#             if is_float(value):
#                 rows = [row for row in rows if apply_compare(m, row, column, value)]
#             elif value is not None:
#                 rows = apply_regex(rows, column, value)
#     sort_column = filter_settings.sort_column
#     sort_reverse = filter_settings.sort_reverse
#     if sort_column is not None:
#         # Check if the sort column index is invalid, and if so reset it to 0
#         if int(sort_column) >= len(rows):
#             sort_column = 0
#         rows = sorted(
#             rows,
#             key=lambda x: human_sort_key(x[int(sort_column)]),
#             reverse=sort_reverse,
#         )
#     safe_name = re.sub("[^A-Za-z0-9]", "-", result.name)
#     filename = f"{safe_name}-mgwatch-filtered.tsv"
#     response = HttpResponse(content_type="text/tab-separated-values")
#     response["Content-Disposition"] = f'attachment; filename="{filename}"'
#     writer = csv.writer(response, delimiter="\t")
#     writer.writerow(headers)
#     for row in rows:
#         writer.writerow(row)
#     return response
