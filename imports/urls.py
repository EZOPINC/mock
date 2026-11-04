from django.urls import path
from . import views

app_name = "imports"
urlpatterns = [
    path("", views.upload, name="upload"),
    path("<uuid:token>/", views.preview, name="preview"),
    path("<uuid:token>/confirm/", views.confirm, name="confirm"),
    path("<uuid:token>/cancel/", views.cancel, name="cancel"),
    path("completed/<int:batch_id>/", views.complete, name="complete"),
]
