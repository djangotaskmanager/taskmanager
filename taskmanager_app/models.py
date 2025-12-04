from django.db import models
from django.db.models import Subquery, OuterRef
from django.db.models.functions import Lower
from django.urls import reverse

from colorfield.fields import ColorField
from martor.models import MartorField
from taggit_selectize.managers import TaggableManager
from taggit.models import GenericTaggedItemBase, TaggedItemBase

DO_NOT_OVERRULE = "do_not_overrule"
USE_TODAYS_DATE = "use_todays_date"
DEPENDENT_ON = "dependent_on"

DATE_OVERRULE_CHOICES = (
    (DO_NOT_OVERRULE, "Do not overrule"),
    (USE_TODAYS_DATE, "Use today's date"),
    (DEPENDENT_ON, "Dependent on…"),
)

DATE_TYPE_CHOICES = (
    ("date_start_earliest", "Start earliest"),
    ("date_start_latest", "Start latest"),
    ("date_due", "Due date"),
)


class TodoItem_tag(GenericTaggedItemBase, TaggedItemBase):
    pass


class MainCategoryItem_main(GenericTaggedItemBase, TaggedItemBase):
    pass


class MainCategoryItem_sub(GenericTaggedItemBase, TaggedItemBase):
    pass


class MainCategoryItem_excluded(GenericTaggedItemBase, TaggedItemBase):
    pass


class ToDoItem(models.Model):
    # Fields cannot be empty
    created_date = models.DateTimeField(auto_now_add=True)
    title = models.CharField(max_length=200, unique=True, blank=False, default=None)

    description = MartorField(blank=True)
    tags = TaggableManager(through=TodoItem_tag, blank=True)
    completed = models.BooleanField(default=False, blank=True)

    date_start_earliest = models.DateField(null=True, blank=True)
    date_start_latest = models.DateField(null=True, blank=True)
    date_due = models.DateField(null=True, blank=True)

    date_start_earliest_depend = models.CharField(
        max_length=100,
        blank=False,
        choices=DATE_OVERRULE_CHOICES,
        default="do_not_overrule",
    )
    date_start_latest_depend = models.CharField(
        max_length=100,
        blank=False,
        choices=DATE_OVERRULE_CHOICES,
        default="do_not_overrule",
    )
    date_due_depend = models.CharField(
        max_length=100,
        blank=False,
        choices=DATE_OVERRULE_CHOICES,
        default="do_not_overrule",
    )

    date_start_earliest_depend_id = models.IntegerField(
        help_text="Item ID (see url of items)",
        blank=True,
        null=True,
        default=None,
    )
    date_start_latest_depend_id = models.IntegerField(
        help_text="Item ID (see url of items)",
        blank=True,
        null=True,
        default=None,
    )
    date_due_depend_id = models.IntegerField(
        help_text="Item ID (see url of items)",
        blank=True,
        null=True,
        default=None,
    )

    date_start_earliest_depend_type = models.CharField(
        max_length=100,
        null=True,
        blank=False,
        choices=DATE_TYPE_CHOICES,
        default="date_due",
    )
    date_start_latest_depend_type = models.CharField(
        max_length=100,
        null=True,
        blank=False,
        choices=DATE_TYPE_CHOICES,
        default="date_due",
    )
    date_due_depend_type = models.CharField(
        max_length=100,
        null=True,
        blank=False,
        choices=DATE_TYPE_CHOICES,
        default="date_due",
    )

    date_start_earliest_depend_shift = models.IntegerField(default=0, blank=True)
    date_start_latest_depend_shift = models.IntegerField(default=0, blank=True)
    date_due_depend_shift = models.IntegerField(default=0, blank=True)

    sorting_priority = models.FloatField(default=0, blank=True)

    def get_absolute_url(self):
        return reverse("item-edit", args=[self.id])

    def __str__(self):
        return f"{self.title}"  # used among other places in the admin interface

    class Meta:
        ordering = [
            "date_start_earliest",
            "date_start_latest",
            "date_due",
            "-sorting_priority",
            Lower("title"),
            "id",
        ]
        indexes = [
            models.Index(fields=["title"]),
            models.Index(fields=["description"]),
            models.Index(fields=["completed"]),
            models.Index(fields=["date_start_earliest"]),
            models.Index(fields=["date_start_latest"]),
            models.Index(fields=["date_due"]),
            models.Index(fields=["date_start_earliest_depend"]),
            models.Index(fields=["date_start_latest_depend"]),
            models.Index(fields=["date_due_depend"]),
            models.Index(fields=["sorting_priority"]),
        ]


class MainCategoryItemQuerySet(models.QuerySet):
    def annotate_first_tag(self):
        return self.annotate(
            first_tag=Subquery(
                self.model.main_category.through.objects.filter(
                    main_category=OuterRef("pk")
                ).values("taggit_tag__name")[:1]
            )
        )


class MainCategoryItem(models.Model):
    created_date = models.DateTimeField(auto_now_add=True)
    main_category = TaggableManager(
        through=MainCategoryItem_main, related_name="main_category_tag"
    )
    sub_categories = TaggableManager(
        through=MainCategoryItem_sub, blank=True, related_name="sub_category_tags"
    )
    excluded_tags = TaggableManager(
        through=MainCategoryItem_excluded, blank=True, related_name="excluded_tags"
    )

    text_field_from_item = models.IntegerField(
        help_text="Item ID to show description text",
        blank=True,
        null=True,
        default=None,
    )
    color = ColorField(default="#FFFFFF")
    sorting_priority = models.FloatField(default=0, blank=True)

    def get_absolute_url(self):
        return reverse(
            "main_category-show", args=[self.main_category.first().name.lower()]
        )

    def __str__(self):
        first_tag_name = self.main_category.all().first()
        return f'Main tag: {first_tag_name.name if first_tag_name else "No Tags"} - Sorting: {self.sorting_priority}'

    # Use the custom queryset manager
    objects = MainCategoryItemQuerySet.as_manager()

    class Meta:
        # Ordering based on the first tag's name
        ordering = [
            "-sorting_priority",
            Lower("main_category__name"),  # Order by the first tag's name
            "id",
        ]
        indexes = [
            models.Index(fields=["created_date"]),
            models.Index(fields=["text_field_from_item"]),
            models.Index(fields=["color"]),
            models.Index(fields=["sorting_priority"]),
        ]
