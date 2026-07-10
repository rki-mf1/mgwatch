# mgw_api/urls.py

from django.urls import path

from . import views

app_name = "mgw_api"
urlpatterns = [
    path("", views.upload_fasta, name="upload_fasta"),
    path("login/", views.user_login, name="login"),
    path("logout/", views.user_logout, name="logout"),
    path("search/", views.upload_fasta, name="upload_fasta"),
    path("signatures/", views.list_signature, name="list_signature"),
    path(
        "process_signature/<int:pk>/", views.process_signature, name="process_signature"
    ),
    path("delete_signature/<int:pk>/", views.delete_signature, name="delete_signature"),
    path("settings/", views.sourmash_settings, name="settings"),
    path("watches/", views.list_watches, name="list_watches"),
    path("results/", views.list_result, name="list_result"),
    path(
        "search/<int:fasta_id>/result/",
        views.search_result,
        name="search_result",
    ),
    path("result/<int:pk>/", views.result_table, name="result_table"),
    path(
        "result/<int:pk>/update_filters/", views.update_filters, name="update_filters"
    ),
    path("result/<int:pk>/update_sort/", views.update_sort, name="update_sort"),
    path("toggle_watch/<int:pk>/", views.toggle_watch, name="toggle_watch"),
    path("delete_result/<int:pk>/", views.delete_result, name="delete_result"),
    path(
        "check_status/<int:fasta_id>/",
        views.check_processing_status,
        name="check_status",
    ),
    path("job_status/<int:fasta_id>/", views.job_status, name="job_status"),
    path(
        "download/result-file/<int:pk>/",
        views.download_result_file,
        name="download_result_file",
    ),
    path(
        "download/signature-file/<int:pk>/",
        views.download_signature_file,
        name="download_signature_file",
    ),
    path(
        "download/full/<int:pk>/", views.download_full_table, name="download_full_table"
    ),
    # path(
    #    "download/filtered/<int:pk>/",
    #    views.download_filtered_table,
    #    name="download_filtered_table",
    # ),
]
