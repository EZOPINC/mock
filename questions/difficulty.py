"""Difficulty choices for imports and the staff review workspace."""
from django.db import models


class Difficulty(models.TextChoices):
    ANY = "", "Any"
    EASY = "easy", "Easy"
    MEDIUM = "medium", "Medium"
    HARD = "hard", "Hard"


RATED_DIFFICULTIES = (Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD)


def normalize_difficulty(value):
    value = value.strip().lower()
    return Difficulty.ANY if value == "any" else value


def difficulty_choice(value):
    normalized = normalize_difficulty(value)
    return normalized if normalized in RATED_DIFFICULTIES else Difficulty.ANY
