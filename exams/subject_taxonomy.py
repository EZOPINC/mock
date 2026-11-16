"""Plan and validate a taxonomy without writes; persist only a complete valid plan."""
from copy import deepcopy
from hashlib import sha256

from django.core.exceptions import ValidationError
from django.utils.text import slugify

from .models import Subject, Part, Module, Submodule, Chapter, Topic


def key(code):
    return code.strip().casefold()


def export_taxonomy():
    """Export all nodes by code, including supported legacy immediate parents."""
    models = {"subjects": Subject, "parts": Part, "modules": Module,
              "submodules": Submodule, "chapters": Chapter, "topics": Topic}
    records = {kind: list(model.objects.order_by("code")) for kind, model in models.items()}
    codes = {model: {node.pk: node.code for node in records[kind]} for kind, model in models.items()}
    data = {"schema_version": 1, "kind": "subject_taxonomy_backup"}
    for kind, nodes in records.items():
        data[kind] = []
        for node in nodes:
            row = {"code": node.code, "name": node.name, "slug": node.slug, "sort_order": node.display_order}
            if kind != "subjects":
                row["subject_code"] = codes[Subject][node.subject_id]
                for field in node.parent_fields:
                    parent_id = getattr(node, field + "_id")
                    if parent_id is not None:
                        parent_model = node._meta.get_field(field).remote_field.model
                        row[field + "_code"] = codes[parent_model][parent_id]
            if kind == "topics":
                row["notes"] = node.notes
            data[kind].append(row)
    return data


def normalize_taxonomy(data):
    """Normalize documented spelling aliases before validation or diagnostics."""
    data = deepcopy(data)
    if not isinstance(data, dict):
        raise ValidationError("Expected a taxonomy object.")
    if "sub_modules" in data:
        if "submodules" in data:
            raise ValidationError("Use either submodules or sub_modules, not both.")
        data["submodules"] = data.pop("sub_modules")
    allowed = {"version", "schema_version", "kind", "subject", "subjects", "scope",
               "parts", "modules", "submodules", "chapters", "topics"}
    if set(data) - allowed:
        raise ValidationError("Unknown taxonomy fields: " + ", ".join(sorted(set(data) - allowed)))
    for kind in ("subjects", "parts", "modules", "submodules", "chapters", "topics"):
        rows = data.get(kind, [])
        if not isinstance(rows, list):
            raise ValidationError(f"{kind} must be an array.")
        for row in rows:
            if not isinstance(row, dict):
                raise ValidationError(f"Each {kind} record must be an object.")
            if "sub_module_code" in row:
                if "submodule_code" in row and row["submodule_code"] != row["sub_module_code"]:
                    raise ValidationError("Conflicting submodule_code and sub_module_code.")
                row["submodule_code"] = row.pop("sub_module_code")
            valid = {"code", "name", "title", "slug", "sort_order"}
            if kind != "subjects":
                valid.add("subject_code")
            valid.update({"modules": {"part_code"}, "submodules": {"module_code"},
                          "chapters": {"submodule_code", "module_code", "part_code"},
                          "topics": {"chapter_code", "module_code", "part_code", "notes"}}.get(kind, set()))
            if set(row) - valid:
                raise ValidationError(f"Unknown {kind} fields: " + ", ".join(sorted(set(row) - valid)))
    return data


def plan_taxonomy(data, *, create_subjects=False, attach_unassigned_chapters=False, attach_submodules=False):
    if not isinstance(data, dict) or data.get("version", data.get("schema_version", 1)) != 1:
        raise ValidationError("Expected a version 1 taxonomy object.")
    data = normalize_taxonomy(data)
    backup = data.get("kind") == "subject_taxonomy_backup"
    # Original single-subject format; scope is descriptive, never a module.
    if "subject" in data:
        subject = data["subject"]
        if isinstance(subject, str):
            subject = {"code": subject}
        if not isinstance(subject, dict):
            raise ValidationError("subject must be a code or object.")
        data["subjects"] = [subject]
        for kind in ("parts", "modules", "submodules", "chapters", "topics"):
            for row in data.get(kind, []):
                row.setdefault("subject_code", subject.get("code"))
    models = {"subjects": Subject, "parts": Part, "modules": Module, "submodules": Submodule, "chapters": Chapter, "topics": Topic}
    catalogue = {kind: {key(obj.code): obj for obj in model.objects.all()} for kind, model in models.items()}
    # Reuse the already loaded nodes for ancestry; avoid thousands of FK queries
    # per file during bulk validation and collision checks.
    by_id = {model: {obj.pk: obj for obj in catalogue[kind].values()} for kind, model in models.items()}
    for kind in models:
        if kind == "subjects":
            continue
        for obj in catalogue[kind].values():
            obj.subject = by_id[Subject][obj.subject_id]
            for field in obj.parent_fields:
                parent_id = getattr(obj, field + "_id")
                if parent_id is not None:
                    setattr(obj, field, by_id[obj._meta.get_field(field).remote_field.model][parent_id])
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
                parent_kind = {"modules": "part", "submodules": "module", "topics": "chapter"}.get(kind)
                if kind == "chapters":
                    chapter_parents = [field for field in obj.parent_fields if row.get(field + "_code")]
                    if row.get("submodule_code"):
                        # Extra Module/Part codes describe ancestry, not additional FKs.
                        submodule = catalogue["submodules"].get(key(row["submodule_code"])) if isinstance(row["submodule_code"], str) else None
                        if submodule:
                            for field, parent in (("module", submodule.module), ("part", submodule.module.part)):
                                context = row.get(field + "_code")
                                if context and (not isinstance(context, str) or parent is None or key(parent.code) != key(context)):
                                    raise ValidationError(f"Conflicting {field}_code ancestry for {code}; select only one immediate parent.")
                        chapter_parents = ["submodule"]
                    if len(chapter_parents) > 1:
                        raise ValidationError(f"Select only one immediate parent for {code}.")
                    parent_kind = chapter_parents[0] if chapter_parents else None
                if kind == "topics" and backup:
                    topic_parents = [field for field in obj.parent_fields if row.get(field + "_code")]
                    if len(topic_parents) > 1:
                        raise ValidationError(f"Select only one immediate parent for {code}.")
                    parent_kind = topic_parents[0] if topic_parents else None
                if kind == "submodules" and not row.get("module_code"):
                    raise ValidationError(f"Sub-module {code} requires module_code.")
                if parent_kind:
                    parent_code = row.get(parent_kind + "_code")
                    if kind == "topics" and not parent_code and not backup:
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
                    initial_submodule = (attach_submodules and kind == "chapters"
                                         and existing.submodule_id is None and existing.part_id is None
                                         and existing.module_id is not None and parents.get("submodule") is not None
                                         and key(existing.module.code) == key(parents["submodule"].module.code))
                    for field in ("subject", *obj.parent_fields):
                        old = getattr(existing, field, None)
                        new = parents.get(field)
                        initial_module_part = kind == "modules" and field == "part" and old is None and new is not None
                        initial_chapter_module = (attach_unassigned_chapters and kind == "chapters"
                                                  and field == "module" and existing.module_id is None
                                                  and existing.part_id is None and existing.submodule_id is None and new is not None)
                        if getattr(old, "code", None) != getattr(new, "code", None) and not (initial_module_part or initial_chapter_module or (initial_submodule and field in ("module", "submodule"))):
                            raise ValidationError(f"Implicit reparenting rejected for {code}.")
                for field in obj.parent_fields:
                    setattr(obj, field, parents.get(field))
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
            if "slug" in row:
                if not isinstance(row["slug"], str) or not row["slug"]:
                    raise ValidationError(f"Invalid slug for {code}.")
                obj.slug = row["slug"]
            # Validate scalar fields even when parents are planned unsaved objects.
            for field in ("code", "name", "slug", "display_order"):
                obj._meta.get_field(field).clean(getattr(obj, field), obj)
            mutable = ("name", "display_order", "slug") + (("notes",) if kind == "topics" else ())
            parent_changed = existing and any(
                getattr(getattr(obj, field, None), "code", None) != getattr(getattr(existing, field, None), "code", None)
                for field in getattr(obj, "parent_fields", ()))
            action = "create" if existing is None else ("update" if parent_changed or any(getattr(obj, f) != getattr(existing, f) for f in mutable) else "unchanged")
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
