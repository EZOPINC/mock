"""Explicitly confirmed, source-context-local multilingual row grouping."""
from collections import defaultdict
from hashlib import sha256
import json
from .taxonomy import topic_identity


def groups_for(rows, approvals):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["values"]["question_number"].strip()].append(row)
    groups = []
    for number, members in grouped.items():
        state = [{"source_row": row["source_row"], "values": row["values"],
                  "subject": row["subject"].code if row["subject"] else None,
                  "topic": topic_identity(row["topic"]),
                  "revision": row["revision"], "translations": row.get("translations", []), "exams": sorted(exam.pk for exam in row["exams"])} for row in members]
        signature = sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        group = {"number": number, "rows": members, "signature": signature,
                 "key": sha256(number.encode()).hexdigest()[:16], "requires_pairing": len(members) > 1,
                 "approved": approvals.get(number) == signature}
        if len(members) > 1:
            languages = [item["language"] for row in members for item in row.get("translations", [row["revision"]])]
            shared = {(row["revision"]["correct_answer"], row["values"]["difficulty_level"].strip(),
                       row["subject"].code if row["subject"] else None,
                       json.dumps(topic_identity(row["topic"])),
                       tuple(sorted(exam.pk for exam in row["exams"]))) for row in members}
            if len(set(languages)) != len(languages) or not all(languages):
                message = "Duplicate question number in the same language (or unresolved language). Correct the rows; they cannot be paired."
            elif len(shared) != 1:
                message = "Ambiguous translation match: answer, difficulty, subject, topic and exams must agree. Resolve this manually; no questions will be merged."
            elif not group["approved"]:
                message = "Confirm the proposed translation pairing for this question number after inspecting every language version."
            else:
                message = None
            if message:
                for row in members:
                    row["errors"].append(message)
        groups.append(group)
    return groups
