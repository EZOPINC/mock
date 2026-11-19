"""Internal import creation cache; never shared across requests or transactions."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from django.core.exceptions import ValidationError
from django.db import connection, models, transaction


_batch = ContextVar("question_creation_batch", default=None)


class CreationBatch:
    def __init__(self):
        self.references = {}
        self.questions = {}

    def remember_reference(self, obj):
        # Call only for records read under the import's locks or just inserted.
        self.references[(obj._meta.label_lower, obj.pk)] = obj


@contextmanager
def creation_batch():
    if not connection.in_atomic_block or _batch.get() is not None:
        raise RuntimeError("Creation batches require their own enclosing import transaction.")
    batch = CreationBatch()
    token = _batch.set(batch)
    try:
        yield batch
    finally:
        _batch.reset(token)


def creation_atomic():
    # Import errors must escape to its outer atomic block; do not recover per row.
    return transaction.atomic(savepoint=_batch.get() is None)


def atomic_creation(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with creation_atomic():
            return function(*args, **kwargs)
    return wrapped


def created_question(pk):
    batch = _batch.get()
    return batch.questions.get(pk) if batch else None


def creation_reference(model, pk):
    batch = _batch.get()
    return batch.references.get((model._meta.label_lower, pk)) if batch else None


def remember_created(obj):
    batch = _batch.get()
    if batch:
        batch.remember_reference(obj)
        if obj._meta.label_lower == "questions.question":
            batch.questions[obj.pk] = obj


class CreationValidationMixin:
    def clean_fields(self, exclude=None):
        batch = _batch.get()
        if batch is None:
            return super().clean_fields(exclude=exclude)
        if self._meta.label_lower == "questions.question":
            owned = self._state.adding or created_question(self.pk) is self
        else:
            owned = created_question(getattr(self, "question_id", None)) is not None
        if not owned:
            return super().clean_fields(exclude=exclude)
        excluded = set(exclude or ())
        cached_fields, errors = set(), {}
        for field in self._meta.fields:
            if not isinstance(field, models.ForeignKey) or field.name in excluded or field.remote_field.limit_choices_to:
                continue
            value = getattr(self, field.attname)
            related = batch.references.get((field.remote_field.model._meta.label_lower, value))
            if related is None:
                continue
            try:
                value = field.to_python(value)
                # Preserve field validation; only the repeated FK existence query
                # is replaced by a transaction-local, locked reference lookup.
                models.Field.validate(field, value, self)
                field.run_validators(value)
                setattr(self, field.name, related)
            except ValidationError as error:
                errors[field.name] = error.error_list
            cached_fields.add(field.name)
        try:
            super().clean_fields(exclude=excluded | cached_fields)
        except ValidationError as error:
            error.update_error_dict(errors)
        if errors:
            raise ValidationError(errors)
