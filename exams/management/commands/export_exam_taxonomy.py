import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from exams.exam_taxonomy import export_catalogue


class Command(BaseCommand):
    help = 'Back up the current exam authority/exam/stage catalogue as reusable versioned JSON.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--overwrite', action='store_true', help='Explicitly replace an existing backup.')

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                data = export_catalogue()
            path = Path(options['file'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w' if options['overwrite'] else 'x', encoding='utf-8') as output:
                output.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        except OSError as error:
            raise CommandError(str(error)) from error
        authorities = data['authorities']
        exams = [exam for authority in authorities for exam in authority['exams']]
        self.stdout.write(f"Exported {len(authorities)} authorities, {len(exams)} exams, {sum(len(exam['stages']) for exam in exams)} stages to {path}")
