"""Presentation helpers for paired translations of the same answer choice."""
from django import template
from types import SimpleNamespace

register = template.Library()


@register.simple_tag
def reading_translations(revision, language="both", reserve_editions=False):
    translations = list(revision.translations.all())
    if language in {"en", "bn"}:
        translations = [item for item in translations if item.language == language]
    if reserve_editions:
        available = {item.language for item in translations}
        for code, label in (("en", "English"), ("bn", "Bengali")):
            if code not in available:
                translations.append(SimpleNamespace(
                    language=code, get_language_display=label, missing_translation=True,
                    question_text="", option_a="", option_b="", option_c="", option_d="", explanation=""))
    return sorted(translations, key=lambda item: ({"en": 0, "bn": 1}.get(item.language, 2), item.language))


@register.filter
def option_text(translation, letter):
    if letter in ("A", "B", "C", "D"):
        return getattr(translation, "option_" + letter.lower())
    return ""
