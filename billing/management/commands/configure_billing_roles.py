from django.core.management.base import BaseCommand
from billing.roles import configure_roles


class Command(BaseCommand):
    help = "Create/update managed billing role groups without assigning users or simulator permissions."

    def handle(self, **options):
        configure_roles()
        self.stdout.write(self.style.SUCCESS("Billing roles configured; no users enrolled."))
