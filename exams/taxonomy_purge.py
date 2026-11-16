"""Explicit, fail-closed deletion plans for unused taxonomy records."""
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim

from .models import Subject, Part, Module, Submodule, Chapter, Topic
from .subject_taxonomy import key


# Children first: no internal PROTECT link needs to be bypassed.
MODELS = {'topics': Topic, 'chapters': Chapter, 'submodules': Submodule,
          'modules': Module, 'parts': Part}


def load_codes(data, *, subject_codes=()):
    if not isinstance(data, dict) or any(data.get(field, 1) != 1 for field in ('version', 'schema_version')):
        raise ValidationError('Expected a version 1 object containing explicit old-code arrays.')
    unknown = set(data) - set(MODELS) - {'version', 'schema_version', 'subject', 'subjects', 'scope'}
    if unknown:
        raise ValidationError('Unknown old-code fields: ' + ', '.join(sorted(unknown)))
    selected_subjects = {key(code) for code in subject_codes}
    declared = data.get('subjects', [])
    if not isinstance(declared, list):
        raise ValidationError('subjects must be an array.')
    declared = list(declared)
    if 'subject' in data:
        declared.append(data['subject'])
    for subject in declared:
        code = subject.get('code') if isinstance(subject, dict) else subject
        if not isinstance(code, str) or not code.strip():
            raise ValidationError('Each declared subject requires a code.')
        if selected_subjects and key(code) not in selected_subjects:
            raise ValidationError('Taxonomy file declares a subject outside --subject selection.')
    result = {}
    for kind in MODELS:
        rows = data.get(kind, [])
        if not isinstance(rows, list):
            raise ValidationError(f'{kind} must be an array of code strings or taxonomy records with explicit codes.')
        codes = []
        for row in rows:
            code = row.get('code') if isinstance(row, dict) else row
            if not isinstance(code, str) or not code.strip():
                raise ValidationError(f'Each {kind} entry requires an explicit nonempty code.')
            if isinstance(row, dict) and 'subject_code' in row:
                subject = row['subject_code']
                if not isinstance(subject, str) or not subject.strip():
                    raise ValidationError(f'Invalid subject_code for {code}.')
                if selected_subjects and key(subject) not in selected_subjects:
                    raise ValidationError(f'{kind} entry {code} is outside --subject selection.')
            codes.append(code)
        if len({key(code) for code in codes}) != len(codes):
            raise ValidationError(f'Duplicate {kind} codes.')
        result[kind] = {key(code) for code in codes}
    if not any(result.values()):
        raise ValidationError('Supply at least one explicit old code; no records are selected implicitly.')
    return result


def concrete_models():
    return [model for model in apps.get_models(include_auto_created=True)
            if not model._meta.proxy and not model._meta.swapped]


def preservation_counts():
    """Include content, joins, assessment history and Subject/Exam records."""
    return {model._meta.label: model._base_manager.count() for model in concrete_models()
            if model._meta.app_label in {'questions', 'previous_year', 'mock_tests', 'practice', 'imports', 'revision'}
            or model in (Subject, apps.get_model('exams', 'Exam'),
                         apps.get_model('exams', 'ExamAuthority'), apps.get_model('exams', 'ExamStage'))}


def plan_purge(subject_codes, codes, *, lock=False):
    requested = {key(code) for code in subject_codes if code.strip()}
    if not requested:
        raise ValidationError('Select subjects explicitly with --subject CODE.')
    subjects = Subject.objects.annotate(_purge_code=Lower(Trim('code'))).filter(_purge_code__in=requested).order_by('pk')
    if lock:
        subjects = subjects.select_for_update()
    subjects = [subject for subject in subjects if key(subject.code) in requested]
    missing = requested - {key(subject.code) for subject in subjects}
    if missing:
        raise ValidationError('Unknown subject codes: ' + ', '.join(sorted(missing)))
    subject_ids = {subject.pk for subject in subjects}
    selected, counts = {}, {}
    for kind, model in MODELS.items():
        # Lock only rows explicitly requested, not all descendants or other subjects.
        rows = model.objects.annotate(_purge_code=Lower(Trim('code'))).filter(_purge_code__in=codes[kind]).order_by('pk')
        if lock:
            rows = rows.select_for_update()
        rows = list(rows)
        missing = codes[kind] - {key(row.code) for row in rows}
        if missing:
            raise ValidationError(f'Unknown {kind} codes: ' + ', '.join(sorted(missing)))
        if any(row.subject_id not in subject_ids for row in rows):
            raise ValidationError(f'{kind} codes include records outside the explicitly selected subjects.')
        selected[model] = {row.pk for row in rows}
        counts[kind] = {subject.code: sum(row.subject_id == subject.pk for row in rows) for subject in subjects}
    links = []
    for source in concrete_models():
        # Explicit and automatic M2M through tables are both included here.
        for field in source._meta.local_fields:
            if not field.is_relation or field.remote_field.model not in selected:
                continue
            target = field.remote_field.model
            if not selected[target]:
                continue
            values = target._base_manager.filter(pk__in=selected[target]).values_list(field.target_field.name, flat=True)
            references = source._base_manager.filter(**{field.attname + '__in': values})
            internal = references.filter(pk__in=selected.get(source, set())).count()
            external = references.exclude(pk__in=selected.get(source, set())).count()
            if internal or external:
                links.append({'field': source._meta.label + '.' + field.name,
                              'on_delete': field.remote_field.on_delete.__name__,
                              'internal': internal, 'external': external,
                              'many_to_many': bool(source._meta.auto_created) or any(
                                  rel.many_to_many and rel.remote_field.through is source
                                  for model in concrete_models() for rel in model._meta.local_many_to_many)})
    return selected, counts, links


def apply_purge(selected, before):
    """Caller holds one atomic transaction and locks from plan_purge."""
    expected = {model._meta.label: len(ids) for model, ids in selected.items() if ids}
    actual = {}
    for model, ids in selected.items():
        if ids:
            _, deleted = model.objects.filter(pk__in=ids).delete()
            for label, count in deleted.items():
                actual[label] = actual.get(label, 0) + count
    if actual != expected:
        raise ValidationError('Unexpected cascade/deletion counts; the transaction is rolled back.')
    after = preservation_counts()
    if before != after:
        raise ValidationError('Protected record counts changed; the transaction is rolled back.')
    return after
