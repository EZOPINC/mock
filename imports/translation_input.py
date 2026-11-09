"""Normalize legacy long rows and explicit per-language extraction columns."""
import re

from django.conf import settings

from .language import infer_language, normalize_language

TEXT_FIELDS = ("question_text", "option_a", "option_b", "option_c", "option_d", "explanation")
REQUIRED_TEXT = TEXT_FIELDS[:-1]
LANGUAGE_COLUMNS = tuple(f"{field}_{code}" for code, label in settings.QUESTION_LANGUAGES for field in TEXT_FIELDS)
EXTRA_METADATA = ("handwritten_mark_unverified", "needs_review", "source_row")


def normalize_translations(values, selected):
    errors, warnings, versions = [], [], []
    for code, label in settings.QUESTION_LANGUAGES:
        translated = {field: values.get(f"{field}_{code}", "") for field in TEXT_FIELDS}
        if any(value.strip() for value in translated.values()):
            for field in REQUIRED_TEXT:
                if not translated[field].strip():
                    errors.append(f"{field}_{code}: complete this language version or clear its entire block.")
            versions.append({"language": code, **translated})
    if versions:
        declared = {part.strip() for part in re.split(r"[,;|]", normalize_language(values.get("language", ""))) if part.strip()}
        available = {version["language"] for version in versions}
        if all(values.get(field, "").strip() for field in REQUIRED_TEXT):
            generic_language = next(iter(declared)) if len(declared) == 1 else infer_language(values)
            if generic_language and generic_language not in available and generic_language in {code for code, label in settings.QUESTION_LANGUAGES}:
                versions.append({"language": generic_language, **{field: values.get(field, "") for field in TEXT_FIELDS}})
                available.add(generic_language)
        configured = {code for code, label in settings.QUESTION_LANGUAGES}
        if declared - configured:
            errors.append("language contains an unsupported code; use configured language codes for explicit translation columns.")
        if declared - available:
            warnings.append("Some declared languages have no available text block; missing translations will not be invented.")
        # A matching legacy block establishes the backward-compatible primary
        # version. Different content must be resolved, never silently discarded.
        matching = [version for version in versions if all(not values.get(field, "").strip() or values[field] == version[field] for field in REQUIRED_TEXT)]
        preferred = next(iter(declared)) if len(declared) == 1 else selected.get("language", "")
        primary = next((version for version in matching if version["language"] == preferred), None)
        primary = primary or (matching[0] if matching else versions[0])
        if not matching and any(values.get(field, "").strip() for field in REQUIRED_TEXT):
            errors.append("Generic question/options differ from the explicit language blocks. Correct or clear the generic values before importing.")
        if not primary["explanation"].strip():
            primary["explanation"] = values.get("explanation", "")
        elif values.get("explanation", "").strip() and values["explanation"] != primary["explanation"]:
            errors.append("Generic and primary-language explanations differ. Resolve the difference explicitly.")
        warnings.append("Explicit language columns represent one master question; available versions are kept together.")
    else:
        language = normalize_language(values.get("language", "").strip() or selected.get("language", ""))
        if not language:
            language = infer_language(values)
            if language:
                warnings.append(f"Language inferred as {language} from question/options text. Check the resolved language or enter an explicit value to override.")
        if not language:
            errors.append("Language could not be inferred. Set a supported code or select a batch default.")
        if any(separator in language for separator in (",", ";", "|")):
            errors.append("Multiple language codes require explicit language columns or one long-format row per language.")
        primary = {"language": language, **{field: values.get(field, "") for field in TEXT_FIELDS}}
        versions = [primary]
    for field in REQUIRED_TEXT:
        if not primary[field].strip():
            errors.append(f"{field}: a value is required.")
    handwritten = values.get("handwritten_mark_unverified", "").strip()
    if handwritten:
        warnings.append(f"Unverified handwritten mark: {handwritten}. Source metadata only; it is NOT a verified answer key.")
    if values.get("needs_review", "").strip().casefold() not in {"", "n", "no", "false", "0"}:
        warnings.append("Source extraction is flagged needs_review. Inspect its text/options and answer manually.")
    revision = {**primary, "correct_answer": values.get("correct_answer", "").strip().upper()}
    return revision, versions, errors, warnings
