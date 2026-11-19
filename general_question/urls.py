from django.urls import path
from . import appearance_views, review_views, views

app_name = "general_questions"
urlpatterns = [
    path("", views.index, name="index"),
    path("manage/", views.manage, name="manage"),
    path("review/", review_views.dashboard, name="dashboard"),
    path("review/questions/", review_views.review_queue, name="review_queue"),
    path("review/questions/<int:question_id>/", review_views.review_question, name="review_question"),
    path("review/questions/<int:question_id>/appearances/new/", appearance_views.edit_appearance, name="add_appearance"),
    path("review/questions/<int:question_id>/appearances/<int:appearance_id>/", appearance_views.edit_appearance, name="edit_appearance"),
    path("manage/<int:batch_id>/", views.manage_batch, name="manage_batch"),
    path("<int:batch_id>/", views.collection, name="collection"),
]
