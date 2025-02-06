# mgw_api/views.py

import csv
import json
import os
import subprocess
import sys
import threading

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate
from django.contrib.auth import login
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import redirect
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_POST

# from .forms import UploadFileForm
# from .models import Choice, Question
from .forms import FastaForm
from .forms import FilterSettingForm
from .forms import LoginForm
from .forms import SettingsForm
from .forms import WatchForm
from .functions import add_sra_metadata
from .functions import apply_compare
from .functions import apply_regex
from .functions import get_branchwater_table
from .functions import get_metadata
from .functions import get_numeric_columns_pandas
from .functions import get_table_data
from .functions import human_sort_key
from .functions import is_float
from .functions import prettify_column_names
from .functions import run_create_signature_and_search
from .models import Fasta
from .models import FilterSetting
from .models import Result
from .models import Settings
from .models import Signature

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
                        uploaded_file_instance = fasta_form.save(commit=False)
                        uploaded_file_instance.user = request.user
                        uploaded_file_instance.name = name
                        uploaded_file_instance.size = uploaded_file.size
                        uploaded_file_instance.processed = False
                        uploaded_file_instance.status = "Processing"
                        uploaded_file_instance.save()
                        thread = threading.Thread(
                            target=run_create_signature_and_search,
                            args=(
                                request.user.id,
                                name,
                                uploaded_file_instance.id,
                                True,
                            ),
                        )
                        thread.start()
                        return JsonResponse(
                            {
                                "success": True,
                                "message": "File submission successful! Processing will happen in the background.",
                                "fasta_id": uploaded_file_instance.id,
                            }
                        )
                except Exception as e:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": f"Error: file submission failed! ... {e}",
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
    return JsonResponse(
        {"status": fasta.status, "fasta_id": fasta_id, "result_pk": fasta.result_pk}
    )


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
            signature.settings_used = current_settings.to_dict()
            signature.submitted = True
            signature.save()
            manage_py_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "manage.py"
            )
            subprocess.Popen(
                [
                    sys.executable,
                    manage_py_path,
                    "create_search",
                    str(request.user.id),
                    signature.name,
                ]
            )
            subprocess.Popen([sys.executable, manage_py_path, "create_search"])
            messages.success(
                request,
                "Signature submission successful! Processing will happen in the background.",
            )
        except Exception as e:
            messages.error(request, f"Error signature submission failed! ... {e}")
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
                signature.submitted = True
                signature.save()
                fasta = signature.fasta
                fasta.processed = False
                fasta.status = "Processing"
                fasta.save()
                thread = threading.Thread(
                    target=run_create_signature_and_search,
                    args=(request.user.id, fasta.name, fasta.id, False),
                )
                thread.start()
                return JsonResponse(
                    {
                        "success": True,
                        "message": "Signature submission successful! Processing will happen in the background.",
                        "fasta_id": fasta.id,
                    }
                )
            except Exception as e:
                return JsonResponse(
                    {
                        "success": False,
                        "error": f"Error: file submission failed! ... {e}",
                    }
                )
    signatures = (
        Signature.objects.filter(user=request.user)
        .prefetch_related("result_set")
        .order_by("-date", "-time")
    )
    for signature in signatures:
        signature.sorted_results = signature.result_set.all().order_by("-date", "-time")
    return render(
        request,
        "mgw_api/list_result.html",
        {"signatures": signatures, "settings_form": settings_form},
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
    else:
        # handle result table
        result = get_object_or_404(Result, pk=pk, user=request.user)
        branchwater_results = get_branchwater_table(
            result, max_rows=settings.MAX_SEARCH_RESULTS
        )
        results_with_metadata = add_sra_metadata(branchwater_results)
        results_with_metadata = prettify_column_names(results_with_metadata)
        filter_settings, created = FilterSetting.objects.get_or_create(
            result=result, user=request.user
        )
        sort_column = filter_settings.sort_column
        sort_reverse = filter_settings.sort_reverse
        results_with_metadata = results_with_metadata.sort_values(
            by=sort_column,
            ascending=not sort_reverse,
            na_position="last",
        )
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

        watch_form = WatchForm(instance=result)
        filter_form = FilterSettingForm(instance=filter_settings)

        if request.headers.get("x-requested-with") == "XMLHttpRequest":
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

        return render(
            request,
            "mgw_api/result_table.html",
            {
                "result": result,
                "headers": headers,
                "rows": rows,
                "watch_form": watch_form,
                "filter_form": filter_form,
                "numeric_columns": numeric_columns,
                "sort_column": sort_column,
                "sort_reverse": sort_reverse,
                "settings_form": settings_form,
            },
        )


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


@login_required
def download_full_table(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    headers, rows = get_table_data(result)
    headers, rows = get_metadata(headers, rows)
    filename = f"{result.name}-MGwatch_complete.tsv".replace(" ", "_")
    response = HttpResponse(content_type="text/tab-separated-values")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response, delimiter="\t")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response


@login_required
def download_filtered_table(request, pk):
    result = get_object_or_404(Result, pk=pk, user=request.user)
    headers, rows = get_table_data(result)
    headers, rows = get_metadata(headers, rows)
    filter_settings = get_object_or_404(FilterSetting, result=result, user=request.user)
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
    sort_column = filter_settings.sort_column
    sort_reverse = filter_settings.sort_reverse
    if sort_column is not None:
        # Check if the sort column index is invalid, and if so reset it to 0
        if int(sort_column) >= len(rows):
            sort_column = 0
        rows = sorted(
            rows,
            key=lambda x: human_sort_key(x[int(sort_column)]),
            reverse=sort_reverse,
        )
    filename = f"{result.name}-MGwatch_filtered.tsv".replace(" ", "_")
    response = HttpResponse(content_type="text/tab-separated-values")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response, delimiter="\t")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return response
