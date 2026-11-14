import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from exams.subject_taxonomy import plan_taxonomy, persist_taxonomy


class Command(BaseCommand):
    help = "Validate/import a versioned subject taxonomy (omitted records are preserved)."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--create-subjects", action="store_true")

    def handle(self, *args, **options):
        try:
            data = json.loads(Path(options["file"]).read_text(encoding="utf-8-sig"))
            with transaction.atomic():
                plan, counts = plan_taxonomy(data, create_subjects=options["create_subjects"])
                if not options["dry_run"]:
                    persist_taxonomy(plan)
        except (OSError, ValueError, TypeError, ValidationError, IntegrityError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write("Dry run (zero writes)" if options["dry_run"] else "Imported")
        for kind, values in counts.items():
            self.stdout.write(f"{kind}: " + ", ".join(f"{action}={count}" for action, count in values.items()))
