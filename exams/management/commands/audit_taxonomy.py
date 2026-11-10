from django.core.management.base import BaseCommand, CommandError

from exams.integrity import taxonomy_integrity_counts


class Command(BaseCommand):
    help = "Read-only taxonomy integrity audit; does not repair or modify records."

    def handle(self, *args, **options):
        counts = taxonomy_integrity_counts()
        for name, count in counts.items():
            self.stdout.write(f"{name}: {count}")
        if any(counts.values()):
            raise CommandError("Taxonomy inconsistencies require review; no records were changed.")
        self.stdout.write(self.style.SUCCESS("Taxonomy integrity audit passed."))
