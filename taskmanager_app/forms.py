from django import forms
from django.forms import ModelForm

from colorfield.fields import ColorWidget
from taggit_selectize.widgets import TagSelectize

from .models import ToDoItem, MainCategoryItem


class DateInput(forms.DateInput):
    input_type = "date"


class ToDoItemForm(ModelForm):
    class Meta:
        model = ToDoItem
        fields = [
            "title",
            "description",
            "tags",
            "completed",
            "date_start_earliest",
            "date_start_latest",
            "date_due",
            "sorting_priority",
            "date_start_earliest_depend",
            "date_start_latest_depend",
            "date_due_depend",
            "date_start_earliest_depend_id",
            "date_start_latest_depend_id",
            "date_due_depend_id",
            "date_start_earliest_depend_type",
            "date_start_latest_depend_type",
            "date_due_depend_type",
            "date_start_earliest_depend_shift",
            "date_start_latest_depend_shift",
            "date_due_depend_shift",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"placeholder": "Title..."}),
            "tags": TagSelectize(attrs={"placeholder": "Tags"}),
            "date_start_earliest": DateInput(),
            "date_start_latest": DateInput(),
            "date_due": DateInput(),
            "date_start_earliest_depend_id": forms.TextInput(
                attrs={"placeholder": "item-id"}
            ),
            "date_start_latest_depend_id": forms.TextInput(
                attrs={"placeholder": "item-id"}
            ),
            "date_due_depend_id": forms.TextInput(attrs={"placeholder": "item-id"}),
        }


class MainCategoryItemEditForm(ModelForm):
    class Meta:
        model = MainCategoryItem
        fields = [
            "main_category",
            "sub_categories",
            "excluded_tags",
            "text_field_from_item",
            "color",
            "sorting_priority",
        ]
        widgets = {
            "main_category": TagSelectize(attrs={"placeholder": "Tags"}),
            "sub_categories": TagSelectize(attrs={"placeholder": "Tags"}),
            "excluded_tags": TagSelectize(attrs={"placeholder": "Tags"}),
            "text_field_from_item": forms.TextInput(attrs={"placeholder": "item-id"}),
            "color": ColorWidget(),
        }


class MainCategoryItemShowForm(ModelForm):
    class Meta:
        model = MainCategoryItem
        fields = [
            "main_category",
            "text_field_from_item",
        ]
