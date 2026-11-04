from django.urls import path
from django.views.generic import TemplateView
from django.contrib.auth.decorators import login_required
from . import views

app_name = 'mock_tests'
urlpatterns = [path("", login_required(TemplateView.as_view(
    template_name="core/placeholder.html",
    extra_context={"title": 'Mock Tests', "description": 'Timed mock tests will be available here in a future milestone.'},
)), name='index'),
    path("preview/", views.preview, name="preview"),
    path("preview/<int:question_id>/", views.preview, name="question_preview"),
]
