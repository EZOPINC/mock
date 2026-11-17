from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, override_settings
from django.urls import include, path


def denied(request):
    raise PermissionDenied("PRIVATE INTERNAL DETAIL")


def failed(request):
    raise RuntimeError("PRIVATE INTERNAL DETAIL")


urlpatterns = [path("denied/", denied), path("failed/", failed), path("", include("config.urls"))]


@override_settings(DEBUG=False, ROOT_URLCONF=__name__)
class ErrorStateTests(SimpleTestCase):
    def test_error_templates_do_not_disclose_exception_details(self):
        self.client.raise_request_exception = False
        for url, status, title in (("/denied/", 403, "This page"), ("/missing-page/", 404, "We couldn’t find"), ("/failed/", 500, "Something went wrong")):
            with self.subTest(status=status):
                response = self.client.get(url)
                self.assertContains(response, title, status_code=status)
                self.assertContains(response, 'id="error-heading"', status_code=status)
                self.assertNotContains(response, "PRIVATE INTERNAL DETAIL", status_code=status)
