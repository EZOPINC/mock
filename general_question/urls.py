from django.urls import path
from . import views

app_name = "general_questions"
urlpatterns = [
    path("", views.index, name="index"),
    path("manage/", views.manage, name="manage"),
    path("manage/<int:batch_id>/", views.manage_batch, name="manage_batch"),
    path("<int:batch_id>/", views.collection, name="collection"),
]
