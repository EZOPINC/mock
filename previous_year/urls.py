from django.urls import path
from . import views

app_name = "previous_year"
urlpatterns = [
    path("", views.index, name="index"),
    path("<slug:authority_slug>/<slug:exam_slug>/",
         views.paper_list, name="paper_list"),
    path("<slug:authority_slug>/<slug:exam_slug>/<int:year>/<int:paper_id>/",
         views.paper_detail, name="paper_detail"),
]
