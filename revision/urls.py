from django.urls import path
from . import exploration_views, session_views, views

app_name = "revision"
urlpatterns = [
    path("questions/<int:question_id>/topics/", exploration_views.question_topics, name="question_topics"),
    path("explore/<str:kind>/<int:node_id>/", exploration_views.explore, name="explore"),
    path("start/", session_views.start, name="start"),
    path("sessions/", session_views.history, name="history"),
    path("sessions/<int:session_id>/", session_views.session_view, name="session"),
    path("sessions/<int:session_id>/questions/<int:question_id>/answer/", session_views.answer, name="answer"),
    path("sessions/<int:session_id>/questions/<int:question_id>/mastery/", session_views.mastery, name="mastery"),
    path("sessions/<int:session_id>/finish/", session_views.finish, name="finish"),
    path("sessions/<int:session_id>/results/", session_views.results, name="results"),
    path("", views.dashboard, name="dashboard"),
    path("saved/<int:pk>/", views.detail, name="detail"),
    path("saved/<int:pk>/manage/", views.manage, name="manage"),
    path("saved/<int:pk>/remove/", views.remove, name="remove"),
    path("questions/<int:question_id>/save/", views.bookmark, {"saved": True}, name="save"),
    path("questions/<int:question_id>/unsave/", views.bookmark, {"saved": False}, name="unsave"),
]
