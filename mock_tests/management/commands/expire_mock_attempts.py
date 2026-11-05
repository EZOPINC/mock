from django.core.management.base import BaseCommand
from django.utils import timezone
from mock_tests.execution import refresh_attempt
from mock_tests.models import MockAttempt


class Command(BaseCommand):
    help = "Finalize overdue mock attempts using frozen answers and marks."

    def handle(self, *args, **options):
        count = 0
        for attempt in MockAttempt.objects.filter(status="in_progress", expires_at__lte=timezone.now()).iterator():
            result = refresh_attempt(attempt.user, attempt.pk)
            count += result.status == "expired"
        self.stdout.write(f"Finalized {count} overdue attempts.")
