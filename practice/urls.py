from django.urls import path
from . import views

app_name = "practice"
urlpatterns = [
    path("", views.index, name="index"),
    path("sessions/<int:session_id>/", views.session_view, name="session"),
    path("sessions/<int:session_id>/questions/<int:question_id>/answer/", views.answer, name="answer"),
    path("sessions/<int:session_id>/summary/", views.summary, name="summary"),
    path("sessions/<int:session_id>/abandon/", views.abandon, name="abandon"),
    path("<slug:authority_slug>/", views.exams, name="exams"),
    path("<slug:authority_slug>/<slug:exam_slug>/", views.subjects, name="subjects"),
    path("<slug:authority_slug>/<slug:exam_slug>/<slug:subject_slug>/", views.configure, name="configure"),
]
