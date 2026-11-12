from copy import deepcopy
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from exams.models import Chapter, Module, Part, Topic
from questions.models import QuestionExam
from questions.services import add_translation, create_question, create_revision, mark_reviewed, publish_question
from questions.tagging import set_question_topics
from .models import ExamPatternSection, ManualRuleQuestion, MockAttempt, SectionSelectionRule
from .rules import eligible_for_rule
from .services import activate_pattern, deactivate_pattern, eligible_question_ids, select_questions, start_attempt, validate_configuration
from .execution import save_response, submit_attempt
from .test_attempts import AttemptFixture


class AdvancedSelectionTests(AttemptFixture):
    def test_bilingual_rules_require_both_published_translations(self):
        self.section.language_mode = "mixed"
        self.section.save()
        question = self.question_at()
        rule = self.rule(subject=self.subject)
        self.assertEqual(eligible_for_rule(rule), set())
        add_translation(question, language="bn", question_text="Bengali edition", option_a="A",
                        option_b="B", option_c="C", option_d="D")
        self.assertEqual(eligible_for_rule(rule), set())
        publish_question(mark_reviewed(question))
        self.assertEqual(eligible_for_rule(rule), {question.pk})

    def test_pattern_add_invalid_parent_shows_validation_errors(self):
        user = get_user_model().objects.create_superuser(username="pattern-admin")
        self.client.force_login(user)
        url = reverse("admin:mock_tests_exampattern_add")
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            "exam": self.exam.pk, "name": "", "version": 1,
            "duration_minutes": 30, "total_questions": 1, "total_marks": 1,
            "default_positive_marks": 1, "default_negative_marks": 0,
            "sections-TOTAL_FORMS": 0, "sections-INITIAL_FORMS": 0,
            "sections-MIN_NUM_FORMS": 0, "sections-MAX_NUM_FORMS": 1000,
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn("name", response.context["adminform"].form.errors)
        self.assertFalse(self.exam.mock_patterns.filter(name="").exists())

    def configure(self, count):
        self.pattern.total_questions = count
        self.pattern.total_marks = count
        self.pattern.save()
        self.section.question_count = count
        self.section.save()

    def question_at(self, topic="default", difficulty="", *, exam=None, published=True):
        question = create_question(subject=self.subject, topic=self.topic if topic == "default" else topic,
            revision={"language": "en", "question_text": "Question", "option_a": "A", "option_b": "B",
                      "option_c": "C", "option_d": "D", "correct_answer": "A", "explanation": "Original explanation"},
            difficulty_level=difficulty)
        QuestionExam.objects.create(question=question, exam=exam or self.exam)
        return publish_question(mark_reviewed(question)) if published else question

    def rule(self, **values):
        data = {"section": self.section, "subject": self.subject, "question_count": 1, "display_order": 1}
        if any(key in values for key in ("part", "module", "chapter", "topic")):
            data.pop("subject")
        return SectionSelectionRule.objects.create(**(data | values))

    def test_exact_topic_and_difficulty_quotas(self):
        self.configure(3)
        other = Topic.objects.create(subject=self.subject, name="Other topic", slug="other")
        questions = [self.question_at(difficulty="Easy"), self.question_at(difficulty=" medium "), self.question_at(other, "Hard")]
        self.rule(topic=self.topic, difficulty="easy")
        self.rule(topic=self.topic, difficulty="medium", display_order=2)
        self.rule(topic=other, difficulty="hard", display_order=3)
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        self.assertEqual(list(attempt.questions.values_list("question_id", flat=True)), [q.pk for q in questions])
        rules = attempt.configuration["sections"][0]["selection_rules"]
        self.assertEqual([rule["difficulty"] for rule in rules], ["easy", "medium", "hard"])
        self.assertEqual([rule["selected_question_ids"] for rule in rules], [[q.pk] for q in questions])
        self.assertEqual(questions[1].published_revision.difficulty_level, " medium ")

    def test_parent_filters_include_every_optional_descendant_path(self):
        part = Part.objects.create(subject=self.subject, name="Part", slug="part")
        module = Module.objects.create(part=part, name="Module", slug="module")
        chapter = Chapter.objects.create(module=module, name="Chapter", slug="chapter")
        direct_chapter = Chapter.objects.create(part=part, name="Direct chapter", slug="direct-chapter")
        root_module = Module.objects.create(subject=self.subject, name="Root module", slug="root-module")
        nodes = [{"part": part}, {"module": module}, {"chapter": chapter}, {"chapter": direct_chapter}, {"module": root_module}]
        questions = []
        for index, node in enumerate(nodes):
            topic = Topic.objects.create(subject=self.subject, name=f"Topic {index}", slug=f"topic-{index}", **node)
            questions.append(self.question_at(topic))
        unclassified = self.question_at(None)
        rule = self.rule(part=part)
        self.assertEqual(eligible_for_rule(rule), {q.pk for q in questions[:4]})
        rule.part, rule.module = None, module
        self.assertEqual(eligible_for_rule(rule), {q.pk for q in questions[1:3]})
        rule.module, rule.chapter = None, direct_chapter
        self.assertEqual(eligible_for_rule(rule), {questions[3].pk})
        rule.chapter, rule.subject = None, self.subject
        self.assertEqual(eligible_for_rule(rule), {q.pk for q in questions} | {unclassified.pk})

    def test_secondary_tags_and_bilingual_count_one_master(self):
        extra = Topic.objects.create(subject=self.subject, name="Secondary", slug="secondary")
        question = self.question_at()
        set_question_topics(question, [self.topic.pk, extra.pk], primary_topic_id=self.topic.pk)
        add_translation(question, language="bn", question_text="বাংলা প্রশ্ন", option_a="এক", option_b="দুই", option_c="তিন", option_d="চার")
        publish_question(mark_reviewed(question))
        rule = self.rule(topic=extra)
        self.assertEqual(eligible_for_rule(rule), {question.pk})
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        self.assertEqual(attempt.questions.count(), 1)
        self.assertEqual(attempt.questions.get().question_revision.translations.count(), 2)

    def test_legacy_topic_filter_still_means_primary_topic(self):
        extra = Topic.objects.create(subject=self.subject, name="Primary", slug="primary")
        question = self.question_at(extra)
        set_question_topics(question, [extra.pk, self.topic.pk], primary_topic_id=extra.pk)
        self.section.topic = self.topic
        self.section.save()
        self.assertEqual(eligible_question_ids(self.section), set())
        self.rule(topic=self.topic)
        self.assertEqual(eligible_question_ids(self.section), {question.pk})

    def test_unspecified_difficulty_and_published_revision_only(self):
        blank = self.question_at(difficulty="")
        named = self.question_at(difficulty="UNSPECIFIED")
        self.question_at(difficulty="unknown")
        rule = self.rule(difficulty="unspecified")
        self.assertEqual(eligible_for_rule(rule), {blank.pk, named.pk})
        create_revision(blank, language="en", question_text="Draft", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D", difficulty_level="hard")
        self.assertIn(blank.pk, eligible_for_rule(rule))

    def test_manual_order_and_random_reservation_across_sections(self):
        self.pattern.total_questions = self.pattern.total_marks = 3
        self.pattern.save()
        second = ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Manual section", question_count=2, display_order=2)
        questions = [self.question_at() for _ in range(3)]
        random = self.rule(topic=self.topic)
        manual = self.rule(section=second, subject=self.subject, selection_mode="manual", question_count=2)
        ManualRuleQuestion.objects.create(rule=manual, question=questions[1], display_order=1)
        ManualRuleQuestion.objects.create(rule=manual, question=questions[0], display_order=2)
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        self.assertEqual(list(attempt.questions.values_list("question_id", flat=True)), [questions[2].pk, questions[1].pk, questions[0].pk])

    def test_overlapping_rule_pools_use_distinct_questions(self):
        self.configure(2)
        extra = Topic.objects.create(subject=self.subject, name="Extra", slug="extra")
        first = self.question_at()
        set_question_topics(first, [self.topic.pk, extra.pk], primary_topic_id=self.topic.pk)
        self.rule(topic=self.topic)
        self.rule(topic=extra, display_order=2)
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)
        second = self.question_at(extra)
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        self.assertEqual(set(attempt.questions.values_list("question_id", flat=True)), {first.pk, second.pk})

    def test_manual_reservation_cannot_starve_narrow_random_rule(self):
        self.configure(2)
        first = self.question_at()
        self.rule(topic=self.topic)
        manual = self.rule(subject=self.subject, selection_mode="manual", display_order=2)
        ManualRuleQuestion.objects.create(rule=manual, question=first)
        with self.assertRaises(ValidationError):
            activate_pattern(self.pattern)
        self.assertFalse(MockAttempt.objects.exists())

    def test_cross_section_manual_duplicates_are_rejected_at_activation(self):
        self.pattern.total_questions = self.pattern.total_marks = 2
        self.pattern.save()
        second = ExamPatternSection.objects.create(language_mode="en", pattern=self.pattern, name="Second", question_count=1, display_order=2)
        question = self.question_at()
        first_rule = self.rule(selection_mode="manual")
        second_rule = self.rule(section=second, selection_mode="manual")
        ManualRuleQuestion.objects.create(rule=first_rule, question=question)
        # Simulate a bypassed application check; activation must still fail closed.
        ManualRuleQuestion(rule=second_rule, question=question).save_base(raw=True, force_insert=True)
        with self.assertRaisesMessage(ValidationError, "more than one rule or section"):
            activate_pattern(self.pattern)

    def test_manual_validation_exam_difficulty_and_duplicate_scope(self):
        first = self.question_at(difficulty="Easy")
        rule = self.rule(difficulty="easy", selection_mode="manual")
        for question in (self.question_at(difficulty="Hard"), self.question_at(difficulty="Easy", exam=self.other_exam), self.question_at(published=False)):
            with self.subTest(question=question.pk), self.assertRaises(ValidationError):
                ManualRuleQuestion.objects.create(rule=rule, question=question)
        ManualRuleQuestion.objects.create(rule=rule, question=first)
        other = self.rule(difficulty="easy", selection_mode="manual", display_order=2)
        with self.assertRaises(ValidationError):
            ManualRuleQuestion.objects.create(rule=other, question=first)

    def test_count_and_filter_constraints(self):
        with self.assertRaises(ValidationError):
            SectionSelectionRule(section=self.section, question_count=1).full_clean()
        invalid = SectionSelectionRule(section=self.section, subject=self.subject, topic=self.topic, question_count=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            invalid.save_base(raw=True, force_insert=True)
        self.rule(question_count=2)
        with self.assertRaisesMessage(ValidationError, "rule question counts"):
            validate_configuration(self.pattern)

    def test_failed_start_after_manual_eligibility_loss_is_atomic(self):
        question = self.question_at()
        rule = self.rule(selection_mode="manual")
        ManualRuleQuestion.objects.create(rule=rule, question=question)
        activate_pattern(self.pattern)
        question.publication_status = "draft"
        question.published_revision = None
        question.save(_workflow=True)
        with self.assertRaises(ValidationError):
            start_attempt(self.user, self.pattern)
        self.assertFalse(MockAttempt.objects.exists())

    def test_rule_filters_replace_section_filters_but_keep_language(self):
        self.section.subject = self.other_subject
        self.section.save()
        question = self.question_at()
        rule = self.rule(subject=self.subject)
        self.assertEqual(eligible_for_rule(rule), {question.pk})
        activate_pattern(self.pattern)
        self.assertEqual(start_attempt(self.user, self.pattern).questions.get().question_id, question.pk)

    def test_frozen_rule_snapshot_revision_and_scoring(self):
        question = self.question_at()
        rule = self.rule(topic=self.topic)
        activate_pattern(self.pattern)
        attempt = start_attempt(self.user, self.pattern)
        row = attempt.questions.get()
        snapshot = deepcopy(attempt.configuration)
        self.topic.name = "Renamed topic"
        self.topic.save()
        extra = Topic.objects.create(subject=self.subject, name="Retagged", slug="retagged")
        set_question_topics(question, [extra.pk], primary_topic_id=extra.pk)
        create_revision(question, language="en", question_text="Later", option_a="A", option_b="B", option_c="C", option_d="D", correct_answer="D")
        publish_question(mark_reviewed(question))
        save_response(self.user, attempt.pk, {"action": "answer", "question_id": row.pk, "answer": "A", "review": False, "version": 0, "token": str(uuid4()), "position": 1})
        result = submit_attempt(self.user, attempt.pk)
        self.assertEqual(result.total_score, 1)
        self.assertEqual(result.configuration, snapshot)
        self.assertEqual(MockAttempt.objects.count(), 1)
        with self.assertRaises(ValidationError):
            start_attempt(self.user, self.pattern)
        self.assertEqual(MockAttempt.objects.count(), 1)
        deactivate_pattern(self.pattern)
        rule.question_count = 2
        with self.assertRaises(ValidationError):
            rule.save()

    def test_admin_rule_inline_and_manual_question_search(self):
        question = self.question_at()
        rule = self.rule(selection_mode="manual")
        user = get_user_model().objects.create_superuser(username="rule-admin")
        self.client.force_login(user)
        response = self.client.get(reverse("admin:mock_tests_exampatternsection_change", args=[self.section.pk]))
        self.assertContains(response, "selection_rules")
        url = reverse("admin:mock_tests_sectionselectionrule_change", args=[rule.pk])
        response = self.client.get(url)
        self.assertContains(response, "manual_questions")
        data = {"section": self.section.pk, "subject": self.subject.pk, "question_count": 1, "selection_mode": "manual", "difficulty": "", "display_order": 1,
                "manual_questions-TOTAL_FORMS": 1, "manual_questions-INITIAL_FORMS": 0,
                "manual_questions-MIN_NUM_FORMS": 0, "manual_questions-MAX_NUM_FORMS": 1000,
                "manual_questions-0-question": question.pk, "manual_questions-0-display_order": 1, "_save": "Save"}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(rule.manual_questions.get().question_id, question.pk)

    def test_invalid_admin_rule_post_returns_validation_errors(self):
        user = get_user_model().objects.create_superuser(username="invalid-rule-admin")
        self.client.force_login(user)
        rule = self.rule()
        response = self.client.post(reverse("admin:mock_tests_sectionselectionrule_change", args=[rule.pk]), {
            "section": self.section.pk, "question_count": 1, "selection_mode": "random", "display_order": 1,
            "manual_questions-TOTAL_FORMS": 0, "manual_questions-INITIAL_FORMS": 0,
            "manual_questions-MIN_NUM_FORMS": 0, "manual_questions-MAX_NUM_FORMS": 1000,
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select exactly one taxonomy filter")
