from django.core.management.base import BaseCommand
from imports.staging import cleanup


class Command(BaseCommand):
    help = "Remove expired private import previews. Run periodically and after interrupted sessions."

    def handle(self, *args, **options):
        self.stdout.write(f"Removed {cleanup()} expired import previews.")
