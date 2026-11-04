from django.urls import path
from . import views

app_name = "exams"
urlpatterns = [
    path("", views.authorities, name="authorities"),
    path("<slug:authority_slug>/", views.exam_list, name="exam_list"),
    path("<slug:authority_slug>/<slug:exam_slug>/", views.exam_detail, name="exam_detail"),
]
