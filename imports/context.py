"""Stable duplicate scope excludes row corrections and taxonomy/language defaults."""
from hashlib import sha256
import json


def mode(data):
    # Legacy staged previews retain their original Previous Year mode.
    return data["selection"].get("import_type", "previous_year")


def exam_ids(data):
    selected = data["selection"]
    return sorted(set(selected.get("exam_ids") or ([selected["exam_id"]] if selected.get("exam_id") else [])))


def context_hash(data, paper=None):
    selected = data["selection"]
    context = {"import_type": mode(data), "exam_ids": exam_ids(data),
               "exam_mapping": selected.get("exam_mapping", "selected") if mode(data) == "general" else "selected"}
    if mode(data) == "previous_year":
        source = selected.get("paper", {})
        context["paper"] = {
            "exam_id": paper.exam_id if paper else selected.get("exam_id"),
            "stage_id": paper.stage_id if paper else source.get("stage_id"),
            "year": paper.year if paper else source.get("year"),
        }
        for field in ("paper_name", "part", "session"):
            value = getattr(paper, field) if paper else source.get(field)
            context["paper"][field] = (value or "").strip().casefold()
    return sha256(json.dumps(context, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
