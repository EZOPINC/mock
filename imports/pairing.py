"""Explicitly confirmed, source-context-local multilingual row grouping."""
from collections import defaultdict
from hashlib import sha256
import json
from django.core.exceptions import ValidationError
from django.utils import timezone

from questions.freshness import resolve_freshness_dates
from questions.models import QuestionKind

from .taxonomy import topic_identity


def groups_for(rows, approvals):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["values"]["question_number"].strip()].append(row)
    groups = []
    today = timezone.localdate()
    for number, members in grouped.items():
        state = [{"source_row": row["source_row"], "values": row["values"],
                  "subject": row["subject"].code if row["subject"] else None,
                  "topic": topic_identity(row["topic"]),
                  "secondary_topics": sorted(topic.pk for topic in row.get("secondary_topics", [])),
                  "taxonomy_path": row.get("taxonomy_path", ""),
                  "revision": row["revision"], "translations": row.get("translations", []), "exams": sorted(exam.pk for exam in row["exams"])} for row in members]
        signature = sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        group = {"number": number, "rows": members, "signature": signature,
                 "key": sha256(number.encode()).hexdigest()[:16], "requires_pairing": len(members) > 1,
                 "approved": approvals.get(number) == signature}
        kinds = {row["question_kind"] for row in members if row["question_kind"]}
        group["question_kind"] = next(iter(kinds)) if len(kinds) == 1 else QuestionKind.UNCLASSIFIED
        subject = members[0]["subject"]
        dates = {}
        for field in ("current_as_of", "expires_on"):
            supplied = {row["freshness"][field] for row in members if field in row["freshness"]}
            if len(supplied) > 1:
                for row in members:
                    row["errors"].append(f"Paired language rows must agree on {field} when both supply a value.")
            elif supplied:
                dates[field] = supplied.pop()
        if subject is not None and subject.question_freshness_years is not None:
            try:
                current_as_of, expires_on = resolve_freshness_dates(subject, default_date=today, **dates)
            except ValidationError as error:
                for row in members:
                    row["errors"].extend(error.messages)
            else:
                group["freshness"] = {"current_as_of": current_as_of, "expires_on": expires_on}
                if expires_on <= today:
                    for row in members:
                        row["warnings"].append("This question is expired and will be excluded from new mocks and practice sets.")
        if len(members) > 1:
            languages = [item["language"] for row in members for item in row.get("translations", [row["revision"]])]
            shared = {(row["revision"]["correct_answer"], row["values"]["difficulty_level"].strip(),
                       row["subject"].code if row["subject"] else None,
                       json.dumps(topic_identity(row["topic"])),
                       row.get("taxonomy_path", ""),
                       tuple(sorted(topic.pk for topic in row.get("secondary_topics", []))),
                       tuple(sorted(exam.pk for exam in row["exams"]))) for row in members}
            if len(set(languages)) != len(languages) or not all(languages):
                message = "Duplicate question number in the same language (or unresolved language). Correct the rows; they cannot be paired."
            elif len(shared) != 1:
                message = "Ambiguous translation match: answer, difficulty, subject, topic and exams must agree. Resolve this manually; no questions will be merged."
            elif len(kinds) > 1:
                message = "Paired language rows must agree on question_kind when both supply a value."
            elif not group["approved"]:
                message = "Confirm the proposed translation pairing for this question number after inspecting every language version."
            else:
                message = None
            if message:
                for row in members:
                    row["errors"].append(message)
        groups.append(group)
    return groups
