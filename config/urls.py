from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/question-import/", include("imports.urls")),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("exam-authorities/", include("exams.urls")),
    path("previous-year/", include("previous_year.urls")),
    path("mock-tests/", include("mock_tests.urls")),
    path("practice/", include("practice.urls")),
    path("", include("core.urls")),
]
