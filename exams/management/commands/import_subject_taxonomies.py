"""Sequential folder import using the existing single-file taxonomy workflow."""
import json
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.utils import timezone

from exams.subject_taxonomy import key, normalize_taxonomy, plan_taxonomy, persist_taxonomy


KINDS = ('subjects', 'parts', 'modules', 'submodules', 'chapters', 'topics')


def relationship_warnings(data):
    """Describe file-local gaps without treating optional parents as errors."""
    warnings = []
    for kind in ('parts', 'modules', 'submodules', 'chapters'):
        records = data.get(kind, [])
        if not isinstance(records, list):
            continue  # The authoritative importer will report malformed arrays.
        parent_field = kind[:-1] + '_code'
        referenced = {key(row[parent_field]) for child in KINDS
                      for row in (data.get(child, []) if isinstance(data.get(child, []), list) else [])
                      if isinstance(row, dict) and isinstance(row.get(parent_field), str)}
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get('code'), str):
                continue
            if key(row['code']) not in referenced:
                warnings.append(f'{kind} {row["code"]}: no children reference this code in this file; other files/database records may contain them.')
            if kind == 'chapters' and not any(row.get(field) for field in ('submodule_code', 'module_code', 'part_code')):
                warnings.append(f'Chapter {row["code"]}: no intermediate parent code; imports directly under Subject (valid skipped-level path).')
    return warnings


class Command(BaseCommand):
    help = 'Import subject taxonomy JSON files in filename order, one transaction per file, with a JSONL results log.'

    def add_arguments(self, parser):
        parser.add_argument('directory', nargs='?', default=str(settings.BASE_DIR / 'Data' / 'Subjects'))
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--create-subjects', action='store_true')
        parser.add_argument('--attach-unassigned-chapters', action='store_true')
        parser.add_argument('--attach-submodules', action='store_true')
        parser.add_argument('--include-backups', action='store_true', help='Also process combined subject_taxonomy_backup files.')
        parser.add_argument('--log-file', help='New UTF-8 JSONL log file. Existing files are never overwritten.')

    def handle(self, *args, **options):
        directory = Path(options['directory']).resolve()
        if not directory.is_dir():
            raise CommandError(f'Taxonomy directory does not exist: {directory}')
        files = sorted((path for path in directory.iterdir() if path.is_file() and path.suffix.lower() == '.json'),
                       key=lambda path: (path.name.casefold(), path.name))
        if not files:
            raise CommandError(f'No JSON files found in {directory}')
        stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
        log_path = Path(options['log_file']) if options['log_file'] else (
            settings.BASE_DIR / 'logs' / 'taxonomy-import' / f'bulk-{stamp}-{uuid4().hex[:8]}.jsonl')
        log_path = log_path.resolve()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = log_path.open('x', encoding='utf-8')
        except OSError as error:
            raise CommandError(f'Cannot create a new results log: {error}') from error
        self.stdout.write(f'Log: {log_path}')
        totals = {kind: dict(create=0, update=0, unchanged=0) for kind in KINDS}
        successes = failures = skipped = 0
        def write(record):
            log.write(json.dumps({'timestamp': timezone.now().isoformat(), **record}, ensure_ascii=False) + '\n')
            log.flush()
        try:
            with log:
                write({'event': 'start', 'directory': str(directory), 'files': [path.name for path in files],
                       'dry_run': options['dry_run'], 'create_subjects': options['create_subjects'],
                       'attach_unassigned_chapters': options['attach_unassigned_chapters'],
                       'attach_submodules': options['attach_submodules'],
                       'include_backups': options['include_backups']})
                for path in files:
                    result = {'event': 'file', 'file': path.name, 'warnings': []}
                    try:
                        data = json.loads(path.read_text(encoding='utf-8-sig'))
                        if isinstance(data, dict) and data.get('kind') == 'subject_taxonomy_backup' and not options['include_backups']:
                            result.update(status='skipped', reason='Combined backup excluded; use --include-backups explicitly.')
                            skipped += 1
                        else:
                            data = normalize_taxonomy(data)
                            result['warnings'] = relationship_warnings(data)
                            with transaction.atomic():
                                plan, counts = plan_taxonomy(data, create_subjects=options['create_subjects'],
                                                            attach_unassigned_chapters=options['attach_unassigned_chapters'],
                                                            attach_submodules=options['attach_submodules'])
                                if not options['dry_run']:
                                    persist_taxonomy(plan)
                            result.update(status='validated' if options['dry_run'] else 'imported', counts=counts)
                            for kind, actions in counts.items():
                                for action, count in actions.items():
                                    totals[kind][action] += count
                            successes += 1
                    except (OSError, ValueError, TypeError, AttributeError, ValidationError, DatabaseError) as error:
                        result.update(status='failed', error=str(error), error_type=type(error).__name__)
                        failures += 1
                    write(result)
                    self.stdout.write(f'{result["status"].upper()}: {path.name} ({len(result["warnings"])} warnings)')
                    if result.get('error'):
                        self.stdout.write('  ' + result['error'])
                summary = {'event': 'summary', 'successful': successes, 'failed': failures, 'skipped': skipped,
                           'dry_run': options['dry_run'], 'totals': totals}
                write(summary)
        except OSError as error:
            raise CommandError(f'Log write failed; earlier successful file imports may already be committed. {error}') from error
        self.stdout.write(f'Completed: successful={successes}, failed={failures}, skipped={skipped}. Log: {log_path}')
        if options['dry_run']:
            self.stdout.write('Dry run: zero database writes. Each file was checked against the current database independently.')
        for kind, actions in totals.items():
            self.stdout.write(kind + ': ' + ', '.join(f'{action}={count}' for action, count in actions.items()))
        if failures:
            raise CommandError(f'{failures} file(s) failed. See {log_path}; successful apply-mode files remain committed.')
