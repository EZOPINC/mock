"""Plan and validate a taxonomy without writes; persist only a complete valid plan."""
from copy import deepcopy
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .models import Subject, Module, Chapter, Topic


def key(code):
    return code.strip().casefold()


def plan_taxonomy(data, *, create_subjects=False):
    if not isinstance(data, dict) or data.get("version", 1) != 1:
        raise ValidationError("Expected a version 1 taxonomy object.")
    data = deepcopy(data)
    # Original single-subject format; scope is descriptive, never a module.
    if "subject" in data:
        subject = data["subject"]
        if isinstance(subject, str):
            subject = {"code": subject}
        if not isinstance(subject, dict):
            raise ValidationError("subject must be a code or object.")
        data["subjects"] = [subject]
        for kind in ("modules", "chapters", "topics"):
            for row in data.get(kind, []):
                row.setdefault("subject_code", subject.get("code"))
    models = {"subjects": Subject, "modules": Module, "chapters": Chapter, "topics": Topic}
    catalogue = {kind: {key(obj.code): obj for obj in model.objects.all()} for kind, model in models.items()}
    plan, counts = [], {kind: dict(create=0, update=0, unchanged=0) for kind in models}
    for kind, model in models.items():
        rows = data.get(kind, [])
        if not isinstance(rows, list):
            raise ValidationError(f"{kind} must be an array.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("code"), str) or not row["code"].strip():
                raise ValidationError(f"Each {kind} record requires a code.")
            code = row["code"].strip()
            if key(code) in seen:
                raise ValidationError(f"Duplicate {kind} code: {code}.")
            seen.add(key(code))
            existing = catalogue[kind].get(key(code))
            obj = deepcopy(existing) if existing else model(code=code)
            if kind == "subjects" and existing is None and not create_subjects:
                raise ValidationError(f"Unknown subject code: {code}. Use --create-subjects explicitly.")
            if kind != "subjects":
                subject_code = row.get("subject_code")
                if not isinstance(subject_code, str) or key(subject_code) not in catalogue["subjects"]:
                    raise ValidationError(f"Unknown subject_code for {code}: {subject_code}.")
                subject = catalogue["subjects"][key(subject_code)]
                parents = {"subject": subject}
                parent_kind = {"chapters": "module", "topics": "chapter"}.get(kind)
                if parent_kind:
                    parent_code = row.get(parent_kind + "_code")
                    if kind == "topics" and not parent_code:
                        raise ValidationError(f"Topic {code} requires chapter_code.")
                    if parent_code:
                        if not isinstance(parent_code, str):
                            raise ValidationError(f"Invalid parent code for {code}.")
                        parent = catalogue[parent_kind + "s"].get(key(parent_code))
                        if parent is None:
                            raise ValidationError(f"Missing {parent_kind} parent {parent_code} for {code}.")
                        if key(parent.subject.code) != key(subject.code):
                            raise ValidationError(f"Cross-subject parent for {code}.")
                        parents[parent_kind] = parent
                if existing:
                    for field in ("subject", *obj.parent_fields):
                        old = getattr(existing, field, None)
                        new = parents.get(field)
                        if getattr(old, "code", None) != getattr(new, "code", None):
                            raise ValidationError(f"Implicit reparenting rejected for {code}.")
                for field, parent in parents.items():
                    setattr(obj, field, parent)
            name = row.get("name", row.get("title", existing.name if existing else None))
            if not isinstance(name, str) or not name.strip():
                raise ValidationError(f"A display name is required for {code}.")
            obj.name = name.strip()
            order = row.get("sort_order", existing.display_order if existing else 0)
            if type(order) is not int or order < 0:
                raise ValidationError(f"Invalid sort_order for {code}.")
            obj.display_order = order
            if kind == "topics":
                obj.notes = row.get("notes", existing.notes if existing else "")
                if not isinstance(obj.notes, str):
                    raise ValidationError(f"Invalid notes for {code}.")
            if not existing:
                obj.slug = (slugify(obj.name)[:140] or "taxonomy") + "-" + sha256(code.encode()).hexdigest()[:16]
            # Validate scalar fields even when parents are planned unsaved objects.
            for field in ("code", "name", "slug", "display_order"):
                obj._meta.get_field(field).clean(getattr(obj, field), obj)
            mutable = ("name", "display_order") + (("notes",) if kind == "topics" else ())
            action = "create" if existing is None else ("update" if any(getattr(obj, f) != getattr(existing, f) for f in mutable) else "unchanged")
            counts[kind][action] += 1
            catalogue[kind][key(code)] = obj
            plan.append((obj, action))
    # Include omitted existing records in collision checks, without saving or
    # allocating database sequence values during a dry run.
    for kind, records in catalogue.items():
        names, slugs = set(), set()
        for obj in records.values():
            parent_field = next((f for f in getattr(obj, "parent_fields", ())
                                 if getattr(obj, f, None) is not None), "subject")
            parent = getattr(obj, parent_field, None)
            scope = (parent_field, getattr(parent, "code", None))
            signature = (scope, obj.name.strip().lower())
            slug_signature = (scope, obj.slug)
            if kind == "subjects":
                slug_signature = obj.slug
            if (kind != "subjects" and signature in names) or slug_signature in slugs:
                raise ValidationError(f"Duplicate name or slug in parent scope: {obj.code}.")
            names.add(signature)
            slugs.add(slug_signature)
    return plan, counts


def persist_taxonomy(plan):
    for obj, action in plan:
        if action == "unchanged":
            continue
        for field in ("subject", *getattr(obj, "parent_fields", ())):
            parent = getattr(obj, field, None)
            if parent is not None:
                setattr(obj, field, parent)
        obj.full_clean()
        obj.save()
