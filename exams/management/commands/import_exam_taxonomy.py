import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from exams.exam_taxonomy import plan_catalogue, persist_catalogue


class Command(BaseCommand):
    help = 'Restore/upsert an exam authority/exam/stage catalogue by scoped codes; never delete omitted records.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            data = json.loads(Path(options['file']).read_text(encoding='utf-8-sig'))
            with transaction.atomic():
                plan, counts = plan_catalogue(data)
                if not options['dry_run']:
                    persist_catalogue(plan)
        except (OSError, ValueError, TypeError, ValidationError, DatabaseError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write('Dry run (zero writes)' if options['dry_run'] else 'Imported')
        for kind, values in counts.items():
            self.stdout.write(f'{kind}: ' + ', '.join(f'{action}={count}' for action, count in values.items()))
