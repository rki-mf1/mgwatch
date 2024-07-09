# mgw_api/urls.py

from django.urls import path
from . import views

app_name = "mgw_api"
urlpatterns = [
    path("", views.upload_fasta, name="upload_fasta"),
    path("login/", views.user_login, name="login"),
    path("signup/", views.user_signup, name="signup"),
    path("logout/", views.user_logout, name="logout"),
    path("uploads/", views.upload_fasta, name="upload_fasta"),
    path("signatures/", views.list_signature, name="list_signature"),
    path("process_signature/<int:pk>/", views.process_signature, name="process_signature"),
    path("delete_signature/<int:pk>/", views.delete_signature, name="delete_signature"),
    path("settings/", views.settings, name="settings"),
    path("results/", views.list_result, name="list_result"),
    path("results/<int:pk>/", views.result_table, name="result_table"),
    path("delete_result/<int:pk>/", views.delete_result, name="delete_result"),
    #path("", views.HomeView.as_view(), name="index"),
    #path("advanced/", views.AdvancedView.as_view(), name="advanced"),
    #path("about/", views.AboutView.as_view(), name="about"),
    #path("contact/", views.ContactView.as_view(), name="contact"),
    #path("examples/", views.ExamplesView.as_view(), name="examples"),
    #path("<int:pk>/", views.DetailView.as_view(), name="detail"),               # ex: /polls/5/
    #path("<int:pk>/results/", views.ResultsView.as_view(), name="results"),     # ex: /polls/5/results/
    # for specific URLS e.g. module/specifics change to: "specifics/<int:question_id>/"
    #path("<int:question_id>/vote/", views.vote, name="vote"),                   # ex: /polls/5/vote/
]
