"""Parse optional semicolon-separated exam appearances without approving them."""
from hashlib import sha256
import json
import re


def normalized_label(value):
    return " ".join(value.split()).casefold()


def appearance_identity(exam_id, exam_name, authority_name, year, stage="", session="", question_number=""):
    exam = exam_id or (normalized_label(exam_name), normalized_label(authority_name))
    values = (exam, year, *(normalized_label(value) for value in (stage, session, question_number)))
    return sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()


def parse_appearance_tags(raw):
    appearances, rejected = [], []
    for part in raw.split(";"):
        part = " ".join(part.split())
        if not part:
            continue
        match = re.fullmatch(r"(.+) ([1-9][0-9]{3})", part)
        if match:
            label, year = match.groups()
            authority, slash, exam = label.partition(" / ")
            if not slash:
                authority, exam = "", label
            if exam and len(exam) <= 200 and len(authority) <= 200:
                appearances.append({"exam_name": exam, "authority_name": authority, "year": int(year)})
                continue
        rejected.append(part)
    return appearances, rejected
