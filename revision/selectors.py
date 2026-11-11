"""User-scoped bank queries; content is hydrated only after visibility and pagination."""
from django.db.models import Case, Count, Exists, F, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.db.models.functions import Lower, Trim
from exams.models import Topic
from mock_tests.models import AttemptQuestion
from questions.eligibility import CONTENT_FIELDS
from questions.models import Question, QuestionExam, QuestionTopic, QuestionTranslation
from questions.services import published_questions
from .models import SavedQuestion


def valid_translations():
    rows = QuestionTranslation.objects.filter(question_id=F("revision__question_id"))
    for field in CONTENT_FIELDS:
        rows = rows.annotate(**{f"_trim_{field}": Trim(field)}).exclude(**{f"_trim_{field}": ""})
        # Match Python str.strip() for whitespace-only imported values too.
        rows = rows.exclude(**{field + "__regex": r"^\s*$"})
    return rows


def visible_questions(user):
    """SQL equivalent of mixed-language eligibility, with an open-mock guard."""
    translations = valid_translations().filter(revision_id=OuterRef("published_revision_id"), question_id=OuterRef("pk"))
    primary = translations.filter(language=OuterRef("published_revision__language"),
        **{field: OuterRef("published_revision__" + field) for field in CONTENT_FIELDS})
    active_exams = QuestionExam.objects.filter(question_id=OuterRef("pk"), exam__is_active=True, exam__authority__is_active=True)
    open_mock = AttemptQuestion.objects.filter(question_id=OuterRef("pk"), attempt__user=user,
                                               attempt__status__in=["created", "in_progress"])
    return (published_questions().select_related(None).prefetch_related(None)
        .filter(published_revision__correct_answer__in=["A", "B", "C", "D"])
        .filter(Exists(active_exams), Exists(primary), Exists(translations.filter(language__in=["en", "bn"])))
        .filter(~Exists(open_mock)))


def bank_rows(user):
    return SavedQuestion.objects.filter(user=user).annotate(
        content_available=Exists(visible_questions(user).filter(pk=OuterRef("question_id"))))


def bank_counts(user):
    return SavedQuestion.objects.filter(user=user).aggregate(
        total=Count("pk"), reviewed=Count("pk", filter=Q(reviewed_at__isnull=False)),
        mastered=Count("pk", filter=Q(is_mastered=True)))


def topic_scope(values):
    topics = Topic.objects.all()
    paths = {"part": ["part_id", "module__part_id", "chapter__part_id", "chapter__module__part_id"],
             "module": ["module_id", "chapter__module_id"], "chapter": ["chapter_id"], "topic": ["pk"]}
    for kind, fields in paths.items():
        if values.get(kind):
            match = Q()
            for field in fields:
                match |= Q(**{field: values[kind].pk})
            topics = topics.filter(match)
    if values.get("subject"):
        topics = topics.filter(subject=values["subject"])
    return topics


def filter_bank(rows, values):
    if values.get("exam"):
        rows = rows.filter(content_available=True, question__exam_associations__exam=values["exam"])
    if values.get("subject"):
        rows = rows.filter(content_available=True, question__subject=values["subject"])
    if any(values.get(kind) for kind in ("part", "module", "chapter", "topic")):
        tags = QuestionTopic.objects.filter(topic__in=topic_scope(values)).values("question_id")
        rows = rows.filter(content_available=True, question_id__in=tags)
    mastery = values.get("mastery")
    if mastery:
        rows = rows.filter(is_mastered=mastery == "mastered")
    sort = values.get("sort") or "saved_newest"
    if sort.startswith("difficulty"):
        rows = rows.annotate(_difficulty=Case(When(content_available=True,
            then=Lower(Trim("question__published_revision__difficulty_level"))), default=Value("")))
        rows = rows.annotate(_difficulty_rank=Case(
            When(_difficulty__in=["easy", "beginner", "1"], then=Value(1)),
            When(_difficulty__in=["medium", "moderate", "intermediate", "2"], then=Value(2)),
            When(_difficulty__in=["hard", "difficult", "advanced", "3"], then=Value(3)),
            default=Value(4), output_field=IntegerField()),
            _difficulty_unknown=Case(When(_difficulty__in=["easy", "beginner", "1", "medium", "moderate", "intermediate", "2", "hard", "difficult", "advanced", "3"], then=Value(0)), default=Value(1)))
        return rows.order_by("_difficulty_unknown", "-_difficulty_rank" if sort == "difficulty_desc" else "_difficulty_rank", "_difficulty", "-saved_at", "-pk").distinct()
    return rows.order_by("saved_at" if sort == "saved_oldest" else "-saved_at", "pk" if sort == "saved_oldest" else "-pk").distinct()


def with_question_content(questions):
    """Bounded rendering helper for approved English/Bengali content and all tags."""
    translations = valid_translations().filter(language__in=["en", "bn"]).order_by(
        Case(When(language="en", then=0), default=1), "language", "pk")
    return questions.select_related("published_revision", "subject", "topic").prefetch_related(
        Prefetch("published_revision__translations", queryset=translations),
        Prefetch("topic_associations", queryset=QuestionTopic.objects.select_related("topic").order_by("-is_primary", "topic__name")))


def hydrate_content(user, rows):
    ids = [row.question_id for row in rows if row.content_available]
    questions = {q.pk: q for q in with_question_content(visible_questions(user).filter(pk__in=ids))}
    for row in rows:
        row.visible_question = questions.get(row.question_id)
