from django.urls import path
from . import views

app_name = 'mock_tests'
urlpatterns = [
    path("", views.index, name="index"),
    path("preview/", views.preview, name="preview"),
    path("preview/<int:question_id>/", views.preview, name="question_preview"),
    path("tests/<int:pattern_id>/start/", views.test_start, name="start"),
    path("attempts/<int:attempt_id>/", views.attempt_detail, name="attempt_detail"),
    path("attempts/<int:attempt_id>/save/", views.save_answer, name="save_answer"),
    path("attempts/<int:attempt_id>/status/", views.attempt_status, name="attempt_status"),
    path("attempts/<int:attempt_id>/submit/", views.confirm_submit, name="submit"),
    path("attempts/<int:attempt_id>/results/", views.results, name="results"),
    path("<slug:authority_slug>/", views.exam_list, name="exams"),
    path("<slug:authority_slug>/<slug:exam_slug>/", views.pattern_list, name="patterns"),
]
