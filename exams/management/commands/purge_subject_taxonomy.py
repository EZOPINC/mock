import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction

from exams.taxonomy_purge import load_codes, plan_purge, preservation_counts, apply_purge


class Command(BaseCommand):
    help = 'Preview deletion of explicitly listed unused old taxonomy codes; preserve Subjects and all question/history links.'

    def add_arguments(self, parser):
        parser.add_argument('--subject', action='append', required=True, help='Subject code; repeat for multiple subjects.')
        parser.add_argument('--old-codes', help='JSON file of explicit old codes grouped by record type.')
        parser.add_argument('--apply', action='store_true', help='Apply the validated plan atomically; default is preview only.')

    def handle(self, *args, **options):
        if not options['old_codes']:
            raise CommandError('Taxonomy import origin is not recorded in the database. Supply an explicit --old-codes JSON file.')
        try:
            codes = load_codes(json.loads(Path(options['old_codes']).read_text(encoding='utf-8-sig')),
                               subject_codes=options['subject'])
            with transaction.atomic():
                selected, counts, links = plan_purge(options['subject'], codes, lock=options['apply'])
                before = preservation_counts()
                self.stdout.write('APPLY plan' if options['apply'] else 'PREVIEW (zero writes)')
                self.stdout.write('Origin: caller-supplied old codes; database import provenance unavailable.')
                self.stdout.write('Subjects preserved: ' + ', '.join(next(iter(counts.values())).keys()))
                for kind, per_subject in counts.items():
                    self.stdout.write(f'{kind}: {sum(per_subject.values())} ' + json.dumps(per_subject, sort_keys=True))
                for link in links:
                    self.stdout.write(f"Link {link['field']}: internal={link['internal']}, external={link['external']}, on_delete={link['on_delete']}, M2M={link['many_to_many']}")
                self.stdout.write('Cascade effects: none permitted outside the explicit deletion set; no links are detached or nulled.')
                self.stdout.write('Preserved record counts: ' + json.dumps(before, sort_keys=True))
                if any(link['external'] for link in links):
                    raise CommandError('Blocked: targeted rows are referenced outside the deletion set. No records deleted.')
                if options['apply']:
                    after = apply_purge(selected, before)
                    self.stdout.write('Verified unchanged record counts: ' + json.dumps(after, sort_keys=True))
            self.stdout.write('Applied successfully.' if options['apply'] else 'Preview only. Add --apply to execute this explicit plan.')
        except (OSError, ValueError, TypeError, ValidationError, DatabaseError) as error:
            raise CommandError(str(error)) from error
