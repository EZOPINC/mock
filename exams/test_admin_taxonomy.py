from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from .models import Chapter, Module, Part, Subject, Topic


class SubjectInlineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="taxonomy-admin", email="admin@example.test")
        cls.subject = Subject.objects.create(name="Science", code="SCI", slug="science")
        cls.other = Subject.objects.create(name="Other", code="OTH", slug="other")
        cls.part = Part.objects.create(subject=cls.subject, name="Part one", slug="part-one")
        cls.module = Module.objects.create(part=cls.part, name="Nested module", slug="nested-module")
        cls.chapter = Chapter.objects.create(module=cls.module, name="Nested chapter", slug="nested-chapter")
        cls.topic = Topic.objects.create(subject=cls.subject, chapter=cls.chapter, name="Nested topic", slug="nested-topic")
        cls.foreign_module = Module.objects.create(subject=cls.other, name="Foreign module", slug="foreign-module")

    def setUp(self):
        self.client.force_login(self.user)
        self.url = reverse("admin:exams_subject_change", args=[self.subject.pk])

    def test_subject_displays_all_four_inline_lists_and_change_links(self):
        response = self.client.get(self.url)
        for prefix, node in (("parts", self.part), ("modules", self.module), ("chapters", self.chapter), ("topics", self.topic)):
            self.assertContains(response, f'name="{prefix}-TOTAL_FORMS"')
            self.assertContains(response, reverse(f"admin:exams_{node._meta.model_name}_change", args=[node.pk]))
            formset = next(item.formset for item in response.context["inline_admin_formsets"] if item.formset.prefix == prefix)
            self.assertEqual(list(formset.queryset.values_list("pk", flat=True)), [node.pk])
        self.assertTemplateUsed(response, "admin/change_form.html")

    def test_subject_inline_can_create_a_direct_module_without_intermediate_levels(self):
        empty = Subject.objects.create(name="Empty", code="EMPTY", slug="empty")
        data = {"name": empty.name, "code": empty.code, "slug": empty.slug, "display_order": "0"}
        for prefix in ("parts", "modules", "chapters", "topics"):
            data.update({prefix + "-TOTAL_FORMS": "0", prefix + "-INITIAL_FORMS": "0"})
        data.update({"modules-TOTAL_FORMS": "1", "modules-0-name": "Direct module", "modules-0-slug": "direct-module", "modules-0-display_order": "0"})
        response = self.client.post(reverse("admin:exams_subject_change", args=[empty.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Module.objects.filter(subject=empty, name="Direct module", part__isnull=True).exists())

    def test_inline_foreign_parent_is_rejected_by_existing_subject_rules(self):
        response = self.client.get(self.url)
        inline = next(item for item in response.context["inline_admin_formsets"] if item.opts.model is Topic)
        formset_class = type(inline.formset)
        formset = formset_class(data={"topics-TOTAL_FORMS": "1", "topics-INITIAL_FORMS": "0", "topics-0-name": "Invalid", "topics-0-slug": "invalid", "topics-0-display_order": "0", "topics-0-module": self.foreign_module.pk}, instance=self.subject, prefix="topics")
        self.assertFalse(formset.is_valid())
        self.assertFalse(Topic.objects.filter(name="Invalid").exists())

    def test_view_only_staff_cannot_edit_or_add_children(self):
        viewer = get_user_model().objects.create_user(username="viewer", is_staff=True)
        viewer.user_permissions.add(*Permission.objects.filter(content_type__app_label="exams", codename__in=["view_subject", "view_part", "view_module", "view_chapter", "view_topic"]))
        self.client.force_login(viewer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for item in response.context["inline_admin_formsets"]:
            self.assertFalse(item.has_add_permission)
            self.assertFalse(item.has_change_permission)
            self.assertFalse(item.has_delete_permission)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)
