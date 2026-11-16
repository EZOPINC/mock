"""Code-addressed exam catalogue backups, separate from subject taxonomy."""
from copy import deepcopy

from django.core.exceptions import ValidationError

from .models import ExamAuthority, Exam, ExamStage


def export_catalogue():
    authorities = []
    exam_rows, authority_rows = {}, {}
    for node in ExamAuthority.objects.order_by('code'):
        row = {field: getattr(node, field) for field in ('code', 'name', 'slug', 'is_active')}
        row['exams'] = []
        authorities.append(row)
        authority_rows[node.pk] = row
    for node in Exam.objects.order_by('authority__code', 'code'):
        row = {field: getattr(node, field) for field in ('code', 'name', 'slug', 'is_active')}
        row['stages'] = []
        authority_rows[node.authority_id]['exams'].append(row)
        exam_rows[node.pk] = row
    for node in ExamStage.objects.order_by('exam__authority__code', 'exam__code', 'display_order', 'code'):
        exam_rows[node.exam_id]['stages'].append({
            'code': node.code, 'name': node.name, 'display_order': node.display_order})
    return {'schema_version': 1, 'kind': 'exam_taxonomy', 'authorities': authorities}


def plan_catalogue(data):
    if not isinstance(data, dict) or data.get('schema_version') != 1 or data.get('kind') != 'exam_taxonomy':
        raise ValidationError('Expected schema_version 1 and kind "exam_taxonomy".')
    if set(data) - {'schema_version', 'kind', 'authorities'}:
        raise ValidationError('Unknown exam taxonomy fields.')
    models = {'authorities': ExamAuthority, 'exams': Exam, 'stages': ExamStage}
    catalogue = {
        'authorities': {(node.code,): node for node in ExamAuthority.objects.all()},
        'exams': {(node.authority.code, node.code): node for node in Exam.objects.select_related('authority')},
        'stages': {(node.exam.authority.code, node.exam.code, node.code): node
                   for node in ExamStage.objects.select_related('exam__authority')},
    }
    counts = {kind: dict(create=0, update=0, unchanged=0) for kind in models}
    seen = {kind: set() for kind in models}
    plan = []

    def rows(kind, records, scope=(), parent=None):
        if not isinstance(records, list):
            raise ValidationError(f'{kind} must be an array.')
        for row in records:
            if not isinstance(row, dict):
                raise ValidationError(f'Each {kind} entry must be an object.')
            code = row.get('code')
            if not isinstance(code, str) or not code.strip() or code != code.strip():
                raise ValidationError(f'Each {kind} entry requires a nonempty code without outer whitespace.')
            identity = (*scope, code)
            if identity in seen[kind]:
                raise ValidationError(f'Duplicate {kind} code in parent scope: {identity}.')
            seen[kind].add(identity)
            child = {'authorities': 'exams', 'exams': 'stages'}.get(kind)
            mutable = ('name', 'display_order') if kind == 'stages' else ('name', 'slug', 'is_active')
            if set(row) - {'code', *mutable, *([child] if child else [])}:
                raise ValidationError(f'Unknown fields for {kind} code {code}.')
            existing = catalogue[kind].get(identity)
            node = deepcopy(existing) if existing else models[kind](code=code)
            for field in mutable:
                value = row.get(field, getattr(existing, field) if existing else getattr(node, field))
                if field in ('name', 'slug'):
                    if not isinstance(value, str) or not value.strip():
                        raise ValidationError(f'{field} is required for {kind} code {code}.')
                    value = value.strip()
                if field == 'is_active' and type(value) is not bool:
                    raise ValidationError(f'is_active must be true/false for {code}.')
                if field == 'display_order' and (type(value) is not int or value < 0):
                    raise ValidationError(f'display_order must be a nonnegative integer for {code}.')
                setattr(node, field, value)
            for field in ('code', *mutable):
                node._meta.get_field(field).clean(getattr(node, field), node)
            parent_field = {'exams': 'authority', 'stages': 'exam'}.get(kind)
            if parent_field:
                setattr(node, parent_field, parent)
            action = 'create' if existing is None else ('update' if any(
                getattr(node, field) != getattr(existing, field) for field in mutable) else 'unchanged')
            counts[kind][action] += 1
            catalogue[kind][identity] = node
            plan.append((node, parent_field, action))
            if child:
                rows(child, row.get(child, []), identity, node)

    rows('authorities', data.get('authorities'))
    # Include omitted rows when checking actual database slug uniqueness scopes.
    for kind in ('authorities', 'exams'):
        slugs = set()
        for identity, node in catalogue[kind].items():
            signature = (*identity[:-1], node.slug)
            if signature in slugs:
                raise ValidationError(f'Duplicate {kind} slug in parent scope: {signature}.')
            slugs.add(signature)
    return plan, counts


def persist_catalogue(plan):
    for node, parent_field, action in plan:
        if action == 'unchanged':
            continue
        if parent_field:
            setattr(node, parent_field + '_id', getattr(node, parent_field).pk)
        node.full_clean()
        node.save()
