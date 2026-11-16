"""Explicit same-subject Module classification correction; no code/ID changes."""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.db.models import Q
from django.db.models.functions import Lower, Trim
from django.utils.text import slugify
from hashlib import sha256

from exams.models import Subject, Part, Module, Submodule, Chapter, Topic


def by_code(model, code):
    return model.objects.annotate(_code=Lower(Trim('code'))).filter(_code=code.strip().lower())


class Command(BaseCommand):
    help = 'Preview an explicit same-subject Module move between Parts, preserving descendants. Apply only with --apply.'

    def add_arguments(self, parser):
        for name in ('subject', 'module', 'from-part', 'to-part'):
            parser.add_argument('--' + name, required=True)
        parser.add_argument('--create-part', action='store_true')
        parser.add_argument('--part-name', help='Required display name when explicitly creating the destination Part.')
        parser.add_argument('--part-order', type=int, default=0)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                subjects = by_code(Subject, options['subject'])
                modules = by_code(Module, options['module'])
                if options['apply']:
                    subjects = subjects.select_for_update()
                    modules = modules.select_for_update()
                subject = subjects.first()
                module = modules.first()
                if subject is None or module is None or module.subject_id != subject.pk:
                    raise ValidationError('Select an existing Module and its actual Subject by code.')
                source = by_code(Part, options['from_part']).first()
                target = by_code(Part, options['to_part']).first()
                if source is None or source.subject_id != subject.pk:
                    raise ValidationError('The expected source Part must exist within the selected Subject.')
                if target and target.subject_id != subject.pk:
                    raise ValidationError('Destination Part belongs to another Subject.')
                if target and module.part_id == target.pk:
                    self.stdout.write('Unchanged: Module already belongs to the destination Part.')
                    return
                if module.part_id != source.pk:
                    raise ValidationError('Module no longer belongs to --from-part; correction aborted.')
                creating = target is None
                if creating:
                    if not options['create_part'] or not options['part_name'] or not options['part_name'].strip():
                        raise ValidationError('Destination Part does not exist; supply --create-part and --part-name explicitly.')
                    code = options['to_part'].strip()
                    target = Part(subject=subject, code=code, name=options['part_name'].strip(), display_order=options['part_order'],
                                  slug=(slugify(options['part_name'])[:140] or 'part') + '-' + sha256(code.encode()).hexdigest()[:16])
                    target.full_clean()
                chapter_ids = Chapter.objects.filter(Q(module=module) | Q(submodule__module=module)).values('pk')
                self.stdout.write('APPLY' if options['apply'] else 'PREVIEW (zero writes)')
                self.stdout.write(f'Part: {"create" if creating else "reuse"} {target.code} ({target.name})')
                self.stdout.write(f'Module: {module.code}: {source.code} -> {target.code}')
                self.stdout.write(f'Descendants retained: submodules={Submodule.objects.filter(module=module).count()}, '
                                  f'chapters={chapter_ids.count()}, '
                                  f'topics={Topic.objects.filter(Q(module=module) | Q(chapter_id__in=chapter_ids)).count()}')
                if options['apply']:
                    if connection.vendor != 'postgresql':
                        raise ValidationError('Guarded Part reassignment requires PostgreSQL.')
                    if creating:
                        target.save()
                    authorization = f'{module.pk}:{source.pk}:{target.pk}'
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT set_config('exams.module_part_reassignment', %s, true)", [authorization])
                    module.part = target
                    module._part_reassignment = True
                    try:
                        module.save()
                    finally:
                        module._part_reassignment = False
                        if not connection.needs_rollback:
                            with connection.cursor() as cursor:
                                cursor.execute("SELECT set_config('exams.module_part_reassignment', '', true)")
            self.stdout.write('Applied. Existing IDs, codes and descendant links retained.' if options['apply'] else 'Preview only; use --apply to perform this correction.')
        except (ValidationError, DatabaseError) as error:
            raise CommandError(str(error)) from error
