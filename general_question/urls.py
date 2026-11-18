from django.urls import path
from . import review_views, views

app_name = "general_questions"
urlpatterns = [
    path("", views.index, name="index"),
    path("manage/", views.manage, name="manage"),
    path("review/", review_views.dashboard, name="dashboard"),
    path("review/questions/", review_views.review_queue, name="review_queue"),
    path("review/questions/<int:question_id>/", review_views.review_question, name="review_question"),
    path("manage/<int:batch_id>/", views.manage_batch, name="manage_batch"),
    path("<int:batch_id>/", views.collection, name="collection"),
]
