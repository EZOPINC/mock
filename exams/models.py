from django.db import models
from django.core.exceptions import ValidationError
from django.db.models.functions import Lower, Trim


from uuid import uuid4


def part_code():
    return "PART-" + uuid4().hex


def module_code():
    return "MODULE-" + uuid4().hex


def chapter_code():
    return "CHAPTER-" + uuid4().hex


def topic_code():
    return "TOPIC-" + uuid4().hex


def scoped_constraints(model, parent, condition=None):
    return [
        models.UniqueConstraint(fields=(parent, "slug"), condition=condition, name=f"d2_{model}_{parent}_slug"),
        models.UniqueConstraint(parent, Lower(Trim("name")), condition=condition, name=f"d2_{model}_{parent}_name"),
    ]


def code_constraints(model):
    return [models.UniqueConstraint(Lower(Trim("code")), name=f"d2_{model}_code_norm"),
            models.CheckConstraint(condition=~models.Q(code__regex=r"^\s*$"), name=f"d2_{model}_code_required")]


class HierarchyNode(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200)
    display_order = models.PositiveIntegerField(default=0)
    parent_fields = ()

    class Meta:
        abstract = True

    def clean_fields(self, exclude=None):
        parents = [field for field in self.parent_fields if getattr(self, field + "_id") is not None]
        if self.subject_id is None and len(parents) == 1:
            parent_model = self._meta.get_field(parents[0]).remote_field.model
            self.subject_id = parent_model.objects.filter(pk=getattr(self, parents[0] + "_id")).values_list("subject_id", flat=True).first()
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        self.name = self.name.strip()
        if not self.name:
            raise ValidationError({"name": "A name is required."})
        if not self.code or not self.code.strip():
            raise ValidationError({"code": "A taxonomy code is required."})
        parents = [field for field in self.parent_fields if getattr(self, field + "_id") is not None]
        if len(parents) > 1:
            raise ValidationError("Select only one immediate parent; Subject is the ancestry anchor.")
        if parents:
            parent = getattr(self, parents[0])
            root = parent.subject_id
            if self.subject_id is None:
                self.subject_id = root
            elif self.subject_id != root:
                raise ValidationError({parents[0]: "Parent must belong to the selected subject."})
        if self.subject_id is None:
            raise ValidationError({"subject": "Select a subject or an immediate parent."})
        if self.pk:
            fields = ["subject_id", "code"]
            if type(self).__name__ != "Topic":
                fields += [field + "_id" for field in self.parent_fields]
            previous = type(self).objects.filter(pk=self.pk).values(*fields).first()
            if previous and any(previous[field] != getattr(self, field) for field in fields):
                raise ValidationError("Existing parent paths and taxonomy codes cannot change; create a new node instead.")

    def save(self, *args, **kwargs):
        # Run ancestry derivation before required-field validation for legacy callers.
        self.clean()
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        parent = next((getattr(self, field) for field in self.parent_fields if getattr(self, field + "_id")), self.subject)
        return f"{parent}: {self.name}"


class ExamAuthority(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=200, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name_plural = "exam authorities"

    def __str__(self):
        return self.name


class Exam(models.Model):
    authority = models.ForeignKey(ExamAuthority, on_delete=models.PROTECT, related_name="exams")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    slug = models.SlugField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("authority", "code"), name="exams_exam_authority_code_uniq"),
            models.UniqueConstraint(fields=("authority", "slug"), name="exams_exam_authority_slug_uniq"),
        ]

    def __str__(self):
        return f"{self.authority}: {self.name}"


class ExamStage(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.PROTECT, related_name="stages")
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    display_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("display_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(fields=("exam", "code"), name="exams_stage_exam_code_uniq"),
        ]

    def __str__(self):
        return f"{self.exam}: {self.name}"


class Subject(models.Model):
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=200, unique=True)

    class Meta:
        ordering = ("name", "pk")
        constraints = code_constraints("subject")

    def __str__(self):
        return self.name


class Part(HierarchyNode):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="parts")
    code = models.CharField(max_length=50, unique=True, default=part_code, blank=True)

    class Meta:
        ordering = ("subject__name", "display_order", "name", "pk")
        constraints = scoped_constraints("part", "subject") + code_constraints("part")


class Module(HierarchyNode):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="modules", blank=True)
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="modules", null=True, blank=True)
    code = models.CharField(max_length=50, unique=True, default=module_code, blank=True)
    parent_fields = ("part",)

    class Meta:
        ordering = ("subject_id", "display_order", "name", "pk")
        constraints = (scoped_constraints("module", "part", models.Q(part__isnull=False))
            + scoped_constraints("module", "subject", models.Q(part__isnull=True)) + code_constraints("module"))


class Chapter(HierarchyNode):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="chapters", blank=True)
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="chapters", null=True, blank=True)
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name="chapters", null=True, blank=True)
    code = models.CharField(max_length=50, unique=True, default=chapter_code, blank=True)
    parent_fields = ("module", "part")

    class Meta:
        ordering = ("subject_id", "display_order", "name", "pk")
        constraints = (scoped_constraints("chapter", "module", models.Q(module__isnull=False))
            + scoped_constraints("chapter", "part", models.Q(part__isnull=False))
            + scoped_constraints("chapter", "subject", models.Q(module__isnull=True, part__isnull=True))
            + code_constraints("chapter")
            + [models.CheckConstraint(condition=~models.Q(module__isnull=False, part__isnull=False), name="d2_chapter_one_parent")])


class Topic(HierarchyNode):
    subject = models.ForeignKey(Subject, on_delete=models.PROTECT, related_name="topics")
    chapter = models.ForeignKey(Chapter, on_delete=models.PROTECT, related_name="topics", null=True, blank=True)
    module = models.ForeignKey(Module, on_delete=models.PROTECT, related_name="topics", null=True, blank=True)
    part = models.ForeignKey(Part, on_delete=models.PROTECT, related_name="topics", null=True, blank=True)
    code = models.CharField(max_length=50, unique=True, default=topic_code, blank=True)
    parent_fields = ("chapter", "module", "part")

    class Meta:
        ordering = ("name", "pk")
        constraints = (scoped_constraints("topic", "chapter", models.Q(chapter__isnull=False))
            + scoped_constraints("topic", "module", models.Q(module__isnull=False))
            + scoped_constraints("topic", "part", models.Q(part__isnull=False))
            + scoped_constraints("topic", "subject", models.Q(chapter__isnull=True, module__isnull=True, part__isnull=True))
            + code_constraints("topic")
            + [models.CheckConstraint(condition=(models.Q(chapter__isnull=True, module__isnull=True)
                | models.Q(chapter__isnull=True, part__isnull=True)
                | models.Q(module__isnull=True, part__isnull=True)), name="d2_topic_one_parent")])

    def save(self, *args, **kwargs):
        # Keep existing import/create callers and database-level uniqueness behavior.
        self.clean()
        return models.Model.save(self, *args, **kwargs)
