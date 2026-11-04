"""Conservative script-based fallback for the two supported languages."""
import unicodedata


def infer_language(values):
    text = "\n".join(values.get(field, "") for field in (
        "question_text", "option_a", "option_b", "option_c", "option_d",
    ))
    letters = [char for char in text if unicodedata.category(char).startswith("L")]
    if any("BENGALI" in unicodedata.name(char, "") for char in letters):
        return "bn"
    # Greek letters may occur in mathematical English questions. Other scripts
    # must not become English merely because options contain Latin labels.
    if any(not any(script in unicodedata.name(char, "") for script in ("LATIN", "GREEK")) for char in letters):
        return ""
    if any("LATIN" in unicodedata.name(char, "") for char in letters):
        return "en"
    return ""
