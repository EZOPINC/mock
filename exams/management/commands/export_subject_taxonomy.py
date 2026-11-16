import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from exams.subject_taxonomy import export_taxonomy


class Command(BaseCommand):
    help = 'Back up all subjects, parts, modules, sub-modules, chapters and topics for import_subject_taxonomy.'

    def add_arguments(self, parser):
        parser.add_argument('file')
        parser.add_argument('--overwrite', action='store_true', help='Explicitly replace an existing backup.')

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                data = export_taxonomy()
            path = Path(options['file'])
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('w' if options['overwrite'] else 'x', encoding='utf-8') as output:
                output.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        except OSError as error:
            raise CommandError(str(error)) from error
        self.stdout.write('Exported ' + ', '.join(f'{kind}={len(data[kind])}' for kind in (
            'subjects', 'parts', 'modules', 'submodules', 'chapters', 'topics')) + f' to {path}')
