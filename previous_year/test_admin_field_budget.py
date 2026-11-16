from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings
from django.urls import reverse

from .admin import PaperQuestionAdmin
from .models import PaperQuestion, PreviousYearPaper
from .services import publish_paper
from .tests import PaperFixture


class PaperAdminFieldBudgetTests(PaperFixture):
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_superuser(username='paper-budget-admin')
        self.client.force_login(self.user)
        self.rows = []
        for index in range(8):
            question = self.question()
            self.rows.append(PaperQuestion.objects.create(paper=self.paper, question_revision=question.published_revision,
                                                         question_number=str(index + 1), display_order=index + 1))
        self.url = reverse('admin:previous_year_previousyearpaper_change', args=[self.paper.pk])

    def identities(self):
        return list(self.paper.paper_questions.order_by('pk').values_list('pk', 'question_id', 'question_revision_id', 'question_number', 'display_order'))

    def test_small_paper_keeps_all_inlines(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['paper_question_overflow'])
        self.assertEqual(response.context['inline_admin_formsets'][0].formset.initial_form_count(), 8)

    @override_settings(DATA_UPLOAD_MAX_NUMBER_FIELDS=100)
    def test_overflow_link_and_full_metadata_form_save_preserve_all_links(self):
        before = self.identities()
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['inline_admin_formsets'], [])
        self.assertEqual(response.context['paper_question_overflow']['count'], 8)
        link = reverse('admin:previous_year_paperquestion_changelist') + f'?paper__id__exact={self.paper.pk}'
        self.assertContains(response, link)
        self.assertNotContains(response, 'name="paper_questions-TOTAL_FORMS"')
        form = response.context['adminform'].form
        data = {field.html_name: field.value() if field.value() is not None else '' for field in form}
        data.update(instructions='Updated paper instructions', _save='Save')
        self.assertLess(len(data), 100)
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 302)
        self.paper.refresh_from_db()
        self.assertEqual(self.paper.instructions, 'Updated paper instructions')
        self.assertEqual(self.identities(), before)

    def test_filtered_question_list_is_paginated_and_scoped(self):
        other = PreviousYearPaper.objects.create(exam=self.exam, year=2024, paper_name='Other')
        other_row = self.row(paper=other)
        url = reverse('admin:previous_year_paperquestion_changelist')
        with patch.object(PaperQuestionAdmin, 'list_per_page', 3):
            response = self.client.get(url, {'paper__id__exact': self.paper.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cl'].result_count, 8)
        self.assertEqual(len(response.context['cl'].result_list), 3)
        self.assertNotIn(other_row.pk, [row.pk for row in response.context['cl'].result_list])

    def test_single_association_edit_uses_model_validation(self):
        row = self.rows[0]
        url = reverse('admin:previous_year_paperquestion_change', args=[row.pk])
        response = self.client.post(url, {'question_revision': row.question_revision_id,
                                         'question_number': 'Renumbered', 'display_order': row.display_order})
        self.assertEqual(response.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.question_number, 'Renumbered')
        draft = self.question(published=False)
        response = self.client.post(url, {'question_revision': draft.current_revision_id,
                                         'question_number': 'Invalid draft', 'display_order': row.display_order})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['adminform'].form.errors)
        row.refresh_from_db()
        self.assertEqual(row.question_number, 'Renumbered')

    def test_standalone_add_keeps_exam_and_expected_count_guards(self):
        self.paper.expected_question_count = 8
        self.paper.save()
        extra = self.question()
        url = reverse('admin:previous_year_paperquestion_add')
        response = self.client.post(url, {'paper': self.paper.pk, 'question_revision': extra.published_revision_id,
                                         'question_number': '9', 'display_order': 9})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['adminform'].form.errors)
        self.assertEqual(self.paper.paper_questions.count(), 8)

    def test_published_rows_cannot_be_changed_deleted_or_appended(self):
        publish_paper(self.paper)
        before = self.identities()
        row = self.rows[0]
        change = reverse('admin:previous_year_paperquestion_change', args=[row.pk])
        delete = reverse('admin:previous_year_paperquestion_delete', args=[row.pk])
        self.assertEqual(self.client.get(change).status_code, 200)
        self.assertEqual(self.client.post(change, {'question_number': 'Forbidden'}).status_code, 403)
        self.assertEqual(self.client.post(delete, {'post': 'yes'}).status_code, 403)
        extra = self.question()
        response = self.client.post(reverse('admin:previous_year_paperquestion_add'),
                                    {'paper': self.paper.pk, 'question_revision': extra.published_revision_id,
                                     'question_number': '9', 'display_order': 9})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.identities(), before)

    def test_parent_and_child_permissions_are_both_required(self):
        viewer = get_user_model().objects.create_user(username='paper-row-viewer', is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='previous_year', codename='view_paperquestion'))
        self.client.force_login(viewer)
        url = reverse('admin:previous_year_paperquestion_changelist')
        self.assertEqual(self.client.get(url).status_code, 403)
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label='previous_year', codename='view_previousyearpaper'))
        self.assertEqual(self.client.get(url).status_code, 200)
        change = reverse('admin:previous_year_paperquestion_change', args=[self.rows[0].pk])
        self.assertEqual(self.client.get(change).status_code, 200)
        self.assertEqual(self.client.post(change, {}).status_code, 403)
