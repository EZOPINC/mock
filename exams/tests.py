from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from .admin import ChapterInline, ExamStageInline, ModuleInline, PartInline, TopicInline
from .models import Exam, ExamAuthority, ExamStage, Subject, Topic


class TaxonomyFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.authority = ExamAuthority.objects.create(name="Public Commission", code="PC", slug="commission")
        cls.other_authority = ExamAuthority.objects.create(name="Other Commission", code="OC", slug="other")
        cls.exam = Exam.objects.create(authority=cls.authority, name="Clerk Exam", code="CLERK", slug="clerk")
        cls.stage = ExamStage.objects.create(exam=cls.exam, name="Preliminary", code="PRE", display_order=1)
        cls.subject = Subject.objects.create(name="বাংলা", code="BN", slug="bengali")
        cls.topic = Topic.objects.create(subject=cls.subject, name="ব্যাকরণ", slug="grammar")


class TaxonomyModelTests(TaxonomyFixture):
    def test_creation_relationships_and_unicode(self):
        self.assertEqual(connection.vendor, "postgresql")
        self.assertTrue(self.authority.is_active)
        self.assertTrue(self.exam.is_active)
        self.assertEqual(self.exam.authority, self.authority)
        self.assertEqual(self.stage.exam, self.exam)
        self.assertEqual(self.topic.subject, self.subject)
        self.assertEqual(self.authority.exams.get(), self.exam)
        self.assertEqual(self.exam.stages.get(), self.stage)
        self.assertEqual(self.subject.topics.get(), self.topic)
        self.subject.refresh_from_db()
        self.topic.refresh_from_db()
        self.assertEqual(self.subject.name, "বাংলা")
        self.assertEqual(self.topic.name, "ব্যাকরণ")
        for obj in (self.authority, self.exam, self.stage, self.subject, self.topic):
            obj.full_clean()
            self.assertIn(obj.name, str(obj))

    def test_global_uniqueness_at_database_level(self):
        for model, existing in ((ExamAuthority, self.authority), (Subject, self.subject)):
            for field in ("code", "slug"):
                with self.subTest(model=model.__name__, field=field):
                    data = {"name": "Duplicate", "code": "NEW", "slug": "new"}
                    data[field] = getattr(existing, field)
                    with self.assertRaises(IntegrityError), transaction.atomic():
                        model.objects.create(**data)

    def test_scoped_uniqueness_at_database_level(self):
        duplicates = [
            (Exam, {"authority": self.authority, "name": "Duplicate", "code": self.exam.code, "slug": "new"}),
            (Exam, {"authority": self.authority, "name": "Duplicate", "code": "NEW", "slug": self.exam.slug}),
            (ExamStage, {"exam": self.exam, "name": "Duplicate", "code": self.stage.code}),
            (Topic, {"subject": self.subject, "name": "Duplicate", "slug": self.topic.slug}),
        ]
        for model, data in duplicates:
            with self.subTest(model=model.__name__, data=data):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.create(**data)

    def test_same_codes_and_slugs_allowed_under_different_parents(self):
        other_exam = Exam.objects.create(authority=self.other_authority, name="Another", code=self.exam.code, slug=self.exam.slug)
        ExamStage.objects.create(exam=other_exam, name="Another Stage", code=self.stage.code)
        other_subject = Subject.objects.create(name="English", code="EN", slug="english")
        Topic.objects.create(subject=other_subject, name="Grammar", slug=self.topic.slug)
        self.assertEqual(Exam.objects.filter(slug="clerk").count(), 2)

    def test_validation_rejects_duplicate_and_invalid_fields(self):
        duplicate = Exam(authority=self.authority, name="Duplicate", code=self.exam.code, slug="new")
        with self.assertRaises(ValidationError):
            duplicate.full_clean()
        for obj in (
            Subject(name="", code="X", slug="bad slug"),
            ExamStage(exam=self.exam, name="Bad", code="BAD", display_order=-1),
            Topic(subject_id=999999, name="Bad", slug="bad"),
            ExamStage(exam_id=999999, name="Bad", code="BAD"),
        ):
            with self.subTest(model=type(obj).__name__), self.assertRaises(ValidationError):
                obj.full_clean()

    def test_negative_stage_order_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            ExamStage.objects.create(exam=self.exam, name="Bad", code="BAD", display_order=-1)

    def test_relationships_are_protected_for_single_and_bulk_deletion(self):
        for parent in (self.authority, self.exam, self.subject):
            with self.subTest(model=type(parent).__name__):
                with self.assertRaises(ProtectedError):
                    parent.delete()
                with self.assertRaises(ProtectedError):
                    type(parent).objects.filter(pk=parent.pk).delete()
                self.assertTrue(type(parent).objects.filter(pk=parent.pk).exists())

    def test_stage_order_is_deterministic(self):
        later = ExamStage.objects.create(exam=self.exam, name="Final", code="FINAL", display_order=2)
        first = ExamStage.objects.create(exam=self.exam, name="Screening", code="SCREEN", display_order=0)
        self.assertEqual(list(self.exam.stages.all()), [first, self.stage, later])


class TaxonomyPublicTests(TaxonomyFixture):
    def detail_url(self, authority=None, exam=None):
        return reverse("exams:exam_detail", args=[(authority or self.authority).slug, (exam or self.exam).slug])

    def test_authority_list_is_public_and_filters_inactive(self):
        hidden = ExamAuthority.objects.create(name="Hidden Authority", code="HIDDEN", slug="hidden", is_active=False)
        response = self.client.get(reverse("exams:authorities"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.authority.name)
        self.assertContains(response, reverse("exams:exam_list", args=[self.authority.slug]))
        self.assertNotContains(response, hidden.name)
        self.assertTemplateUsed(response, "base.html")

    def test_exam_list_is_public_and_scoped_and_active(self):
        hidden = Exam.objects.create(authority=self.authority, name="Hidden Exam", code="HIDDEN", slug="hidden", is_active=False)
        outsider = Exam.objects.create(authority=self.other_authority, name="Other Exam", code="OTHER", slug="other")
        response = self.client.get(reverse("exams:exam_list", args=[self.authority.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.exam.name)
        self.assertContains(response, self.detail_url())
        self.assertNotContains(response, hidden.name)
        self.assertNotContains(response, outsider.name)

    def test_detail_is_public_and_displays_authority_stages_and_module_links(self):
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        for text in (self.exam.name, self.authority.name, self.stage.name, "Available Modules"):
            self.assertContains(response, text)
        self.assertContains(response, reverse("previous_year:paper_list", args=[self.authority.slug, self.exam.slug]))
        for route in ("mock_tests:index", "practice:index"):
            self.assertContains(response, f'href="{reverse(route)}"')
        self.assertEqual(self.client.get(reverse("previous_year:index")).status_code, 200)
        for route in ("mock_tests:index", "practice:index"):
            self.assertRedirects(self.client.get(reverse(route)), reverse("accounts:login") + "?next=" + reverse(route))

    def test_detail_does_not_show_stages_from_other_exams(self):
        other = Exam.objects.create(authority=self.other_authority, name="Other", code="OTHER", slug="other")
        ExamStage.objects.create(exam=other, name="Other Exclusive Stage", code="OTHER")
        self.assertNotContains(self.client.get(self.detail_url()), "Other Exclusive Stage")

    def test_invalid_or_wrong_parent_urls_return_404(self):
        for args in (("missing",), ("missing", "clerk"), ("commission", "missing"), ("other", "clerk")):
            route = "exams:exam_list" if len(args) == 1 else "exams:exam_detail"
            with self.subTest(args=args):
                self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 404)

    def test_same_slug_resolves_within_its_authority(self):
        other = Exam.objects.create(authority=self.other_authority, name="Distinct Exam", code="CLERK", slug="clerk")
        response = self.client.get(self.detail_url(authority=self.other_authority, exam=other))
        self.assertEqual(response.context["exam"], other)
        self.assertNotContains(response, self.stage.name)

    def test_inactive_exam_returns_404(self):
        self.exam.is_active = False
        self.exam.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_inactive_authority_hides_active_exam_and_listing(self):
        self.authority.is_active = False
        self.authority.save(update_fields=["is_active"])
        for url in (self.detail_url(), reverse("exams:exam_list", args=[self.authority.slug])):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_empty_states(self):
        self.stage.delete()
        self.assertContains(self.client.get(self.detail_url()), "No stages have been listed")
        self.exam.delete()
        self.assertContains(self.client.get(reverse("exams:exam_list", args=[self.authority.slug])), "No exams are available")
        ExamAuthority.objects.all().delete()
        self.assertContains(self.client.get(reverse("exams:authorities")), "No exam authorities are available")

    def test_guest_can_follow_home_to_exam(self):
        self.assertContains(self.client.get(reverse("home")), reverse("exams:authorities"))
        for url in (reverse("exams:authorities"), reverse("exams:exam_list", args=[self.authority.slug]), self.detail_url()):
            self.assertEqual(self.client.get(url).status_code, 200)


class TaxonomyAdminTests(TaxonomyFixture):
    def test_all_models_registered_and_inlines_configured(self):
        for model in (ExamAuthority, Exam, ExamStage, Subject, Topic):
            self.assertTrue(admin.site.is_registered(model))
        self.assertIn(ExamStageInline, admin.site._registry[Exam].inlines)
        self.assertEqual(admin.site._registry[Subject].inlines, (PartInline, ModuleInline, ChapterInline, TopicInline))

    def test_guests_and_students_cannot_access_admin(self):
        url = reverse("admin:exams_exam_changelist")
        self.assertRedirects(self.client.get(url), reverse("admin:login") + "?next=" + url)
        student = get_user_model().objects.create_user(username="student")
        self.client.force_login(student)
        self.assertRedirects(self.client.get(url), reverse("admin:login") + "?next=" + url)

    def test_staff_without_permissions_cannot_manage_taxonomy(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        self.client.force_login(staff)
        for model in (ExamAuthority, Exam, ExamStage, Subject, Topic):
            name = model._meta.model_name
            self.assertEqual(self.client.get(reverse(f"admin:exams_{name}_changelist")).status_code, 403)
            self.assertEqual(self.client.get(reverse(f"admin:exams_{name}_add")).status_code, 403)

    def test_view_only_staff_cannot_add_change_or_delete(self):
        staff = get_user_model().objects.create_user(username="viewer", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(content_type__app_label="exams", codename="view_exam"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(reverse("admin:exams_exam_changelist")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:exams_exam_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:exams_exam_change", args=[self.exam.pk]), {}).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:exams_exam_delete", args=[self.exam.pk]), {"post": "yes"}).status_code, 403)

    def test_superuser_can_manage_all_models_and_render_inlines(self):
        user = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        self.client.force_login(user)
        for obj in (self.authority, self.exam, self.stage, self.subject, self.topic):
            name = obj._meta.model_name
            for suffix, args in (("changelist", []), ("add", []), ("change", [obj.pk])):
                with self.subTest(model=name, page=suffix):
                    self.assertEqual(self.client.get(reverse(f"admin:exams_{name}_{suffix}", args=args)).status_code, 200)

    def test_admin_protected_delete_keeps_parent_and_dependents(self):
        user = get_user_model().objects.create_superuser(username="admin", email="admin@example.test")
        self.client.force_login(user)
        for obj in (self.authority, self.exam, self.subject):
            with self.subTest(model=obj._meta.model_name):
                response = self.client.post(reverse(f"admin:exams_{obj._meta.model_name}_delete", args=[obj.pk]), {"post": "yes"})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["protected"])
                self.assertTrue(type(obj).objects.filter(pk=obj.pk).exists())
