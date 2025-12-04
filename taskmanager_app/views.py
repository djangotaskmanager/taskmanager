import json
import time
import uuid
from datetime import date, datetime, timedelta

import dropbox
from dropbox import exceptions
from django.conf import settings
from django.db.models import Q
from django.db.models import Case, When, Value, DateField, FloatField, CharField
from django.db.models.functions import Lower
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
    View,
)
from martor.utils import LazyEncoder

from .forms import MainCategoryItemEditForm, MainCategoryItemShowForm, ToDoItemForm
from .models import DEPENDENT_ON, USE_TODAYS_DATE, MainCategoryItem, ToDoItem
from .utils import topological_sort

MAX_ATTEMPTS = 60

AT_LEAST_ONE_DATE_FIELD = (
    Q(date_start_earliest__isnull=False)
    | Q(date_start_latest__isnull=False)
    | Q(date_due__isnull=False)
)

WITHOUT_DATE_FIELDS = (
    Q(date_start_earliest__isnull=True)
    & Q(date_start_latest__isnull=True)
    & Q(date_due__isnull=True)
)


def date_is_past(d: date, today: date) -> bool:
    return d is not None and d < today


def date_is_today(d: date, today: date) -> bool:
    return d is not None and d == today


def date_is_within_dates(d: date, start_date: date, end_date: date) -> bool:
    return d is not None and start_date <= d <= end_date


def update_all_dependent_dates():
    """Function updates all dates dependent on other dates"""

    dependency_chain, _, _ = get_date_dependency_chain()

    # Update all date dependencies
    for item_id, fields in dependency_chain[USE_TODAYS_DATE].items():
        ToDoItem.objects.filter(pk=item_id).update(
            **{field: timezone.now().date() for field in fields}
        )

    # DO NOT use bulk_update, as a chain of dependencies will not work correct, hence, the only way is to update one-by-one
    # To circumvent this problem, and to use bulk_update, the dependency-chain-updated dates shall be calculated beforehand
    # which could be done either in get_date_dependency_chain or here.
    for row in dependency_chain[DEPENDENT_ON]:
        # Item does not exist OR field in item is not set
        if (ToDoItem.objects.filter(pk=row["from_id"]).exists()) and (
            from_date := getattr(
                ToDoItem.objects.get(pk=row["from_id"]), row["from_field"]
            )
        ):
            date = from_date + timedelta(days=row["shift_by"])
        else:
            date = datetime(1, 1, 1)

        ToDoItem.objects.filter(pk=row["id"]).update(**{row["field"]: date})


def get_date_dependency_chain(
    return_error_msg: bool = False, form=None, item_id: int = None
):
    """Function to create chain of items with dates dependencies"""

    dependent_items = ToDoItem.objects.filter(
        Q(date_start_earliest_depend__in=[USE_TODAYS_DATE, DEPENDENT_ON])
        | Q(date_start_latest_depend__in=[USE_TODAYS_DATE, DEPENDENT_ON])
        | Q(date_due_depend__in=[USE_TODAYS_DATE, DEPENDENT_ON])
    )

    # Collect items data
    dependency_data = {USE_TODAYS_DATE: {}, DEPENDENT_ON: []}
    for item in dependent_items:
        for field in (
            "date_start_earliest_depend",
            "date_start_latest_depend",
            "date_due_depend",
        ):
            if getattr(item, field) == USE_TODAYS_DATE:
                if item.id not in dependency_data[USE_TODAYS_DATE]:
                    dependency_data[USE_TODAYS_DATE].update({item.id: []})
                dependency_data[USE_TODAYS_DATE][item.id].append(
                    field.replace("_depend", "")
                )
            elif getattr(item, field) == DEPENDENT_ON:
                dependency_data[DEPENDENT_ON].append(
                    {
                        "id": item.id,
                        "field": field.replace("_depend", ""),
                        "from_field": getattr(item, f"{field}_type"),
                        "from_id": getattr(item, f"{field}_id"),
                        "shift_by": getattr(item, f"{field}_shift"),
                    }
                )

    # If function called from edit item; add the selected form data instead of the saved
    if return_error_msg and item_id and form and form.changed_data:
        # Remove current version of item from dependent_items
        dependent_items = [item for item in dependent_items if item.id != item_id]

        # Add new version of item
        item = form.cleaned_data

        for field in (
            "date_start_earliest_depend",
            "date_start_latest_depend",
            "date_due_depend",
        ):
            if item[field] == USE_TODAYS_DATE:
                if item_id not in dependency_data[USE_TODAYS_DATE]:
                    dependency_data[USE_TODAYS_DATE].update({item_id: []})
                dependency_data[USE_TODAYS_DATE][item_id].append(
                    field.replace("_depend", "")
                )
            elif item[field] == DEPENDENT_ON:
                dependency_data[DEPENDENT_ON].append(
                    {
                        "id": item_id,
                        "field": field.replace("_depend", ""),
                        "from_field": item[f"{field}_type"],
                        "from_id": item[f"{field}_id"],
                        "shift_by": item[f"{field}_shift"],
                    }
                )

    # Create unique id-field strings -> dependency_strings = [[child, parent], ...]:
    dependency_strings = [
        (
            [
                str(row["id"]) + "@" + row["field"],
                str(row["from_id"]) + "@" + row["from_field"],
            ]
        )
        for row in dependency_data[DEPENDENT_ON]
    ]

    # Make a topological sort of dependencies and check chain for recursive dependencies
    sorted_strings, error_flag, form = topological_sort(
        dependencies=dependency_strings,
        return_error_msg=return_error_msg,
        form=form,
        item_id=item_id,
    )

    if error_flag:
        return None, error_flag, form

    # Sort dependency chain
    dependency_data[DEPENDENT_ON] = sorted(
        dependency_data[DEPENDENT_ON],
        key=lambda d: sorted_strings.index(str(d["id"]) + "@" + d["field"]),
    )

    return dependency_data, False, form


def autocomplete_titles(request):
    """Function to return list of autocomplete titles when user typing item title"""
    if "term" in request.GET:
        term = request.GET["term"]
        items = ToDoItem.objects.filter(Q(title__icontains=term))
        titles = [item.title for item in items]
        return JsonResponse(titles, safe=False)
    return JsonResponse([], safe=False)


def edit_item_by_title(request, title):
    """Function to return url if user want to access item by title instead of object id"""
    # Get the ToDoItem with the specified title
    item = get_object_or_404(ToDoItem, title=title)

    # Redirect to the item's edit page
    return redirect(item.get_absolute_url())


def completed_state_filter(completed_state: str, data_set: any):
    """Filter function to show all, only completed or only not completed"""
    if completed_state == "completed":
        return data_set.filter(completed=True)
    if completed_state == "not_completed":
        return data_set.filter(completed=False)

    return data_set.all()


def dates_state_filter(dates_state: str, data_set: any):
    """Filter function to show all, only with dates or only without dates"""
    if dates_state == "w_dates":
        return data_set.filter(AT_LEAST_ONE_DATE_FIELD)
    if dates_state == "wo_dates":
        return data_set.filter(WITHOUT_DATE_FIELDS)

    return data_set.all()


def sort_by_date_state_filter(sort_by_date_state: str, data_set: any):
    """Filter function to show items based on dates"""
    today = timezone.now().date()

    if sort_by_date_state == "one_week":
        end_date = today + timedelta(days=7)
        return data_set.filter(
            Q(date_start_earliest__lte=end_date)
            | Q(date_start_latest__lte=end_date)
            | Q(date_due__lte=end_date)
        )
    if sort_by_date_state == "two_weeks":
        end_date = today + timedelta(days=14)
        return data_set.filter(
            Q(date_start_earliest__lte=end_date)
            | Q(date_start_latest__lte=end_date)
            | Q(date_due__lte=end_date)
        )
    if sort_by_date_state == "one_month":
        end_date = today + timedelta(days=30)
        return data_set.filter(
            Q(date_start_earliest__lte=end_date)
            | Q(date_start_latest__lte=end_date)
            | Q(date_due__lte=end_date)
        )

    return data_set.all()


def get_sorted_grouped_todo_items(
    filtered_items,
    main_tag: str,
    sub_category_tags: list,
    excluded_tags: list,
    completed_state: str = None,
    dates_state: str = None,
):
    """Returns a dict containing sub-categories as keys and todo items as values"""

    # Organize related ToDoItems by sub_category_tags and excluded_tags
    related_todo_items = filtered_items.filter(tags__name=main_tag).order_by(
        "-sorting_priority", "title"
    )
    related_todo_items = completed_state_filter(completed_state, related_todo_items)
    related_todo_items = dates_state_filter(dates_state, related_todo_items)
    grouped_todo_items = {}
    items_without_sub_tags = []
    for item in related_todo_items:
        item_tags_all = item.tags.all()
        if any(tag in excluded_tags for tag in item_tags_all):
            continue

        if not any(tag in sub_category_tags for tag in item_tags_all):
            items_without_sub_tags.append(item)
        else:
            for tag in item_tags_all:
                if tag in sub_category_tags:
                    if tag not in grouped_todo_items:
                        grouped_todo_items[tag] = []
                    grouped_todo_items[tag].append(item)

    sorted_grouped_todo_items = dict(
        sorted(grouped_todo_items.items(), key=lambda x: x[0].name)
    )

    if items_without_sub_tags:
        sorted_grouped_todo_items["Other"] = items_without_sub_tags

    return sorted_grouped_todo_items


def filter_item_lists_by_query(query: str, todoitems):
    """Filters a todoitems list by a given query"""

    # Split the query into individual words
    query_words = query.split() if query else [""]

    # Filter cases that include all the words in title, description, or tags
    results = todoitems.filter(
        Q(title__icontains=query_words[0])
        | Q(description__icontains=query_words[0])
        | Q(tags__name__icontains=query_words[0])
    ).distinct()

    for word in query_words[1:]:
        results = results.filter(
            Q(title__icontains=word)
            | Q(description__icontains=word)
            | Q(tags__name__icontains=word)
        ).distinct()

    return results


class SearchResultsView(ListView):
    """View class for search results"""

    model = ToDoItem
    template_name = "taskmanager_app/search_results.html"

    def get_queryset(self):
        # Update all dependent dates in items
        update_all_dependent_dates()

        query = self.request.GET.get("query")
        completed_state = self.request.GET.get("completed_state")
        dates_state = self.request.GET.get("dates_state")

        results = filter_item_lists_by_query(
            query, self.model.objects.prefetch_related("tags")
        )

        results = dates_state_filter(dates_state, results)
        return completed_state_filter(completed_state, results)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["main_categories"] = {
            key: value
            for key, value in zip(
                MainCategoryItem.objects.values_list("main_category__name", flat=True),
                MainCategoryItem.objects.values_list("color", flat=True),
            )
        }
        return context


class SortingView(ListView):
    model = ToDoItem
    template_name = "taskmanager_app/sorting_view.html"

    def get_context_data(self, **kwargs):
        today = timezone.now().date()

        context = super().get_context_data()

        context["today"] = today
        context["one_week_from_now"] = context["today"] + timedelta(days=7)

        context["main_categories"] = {
            key: value
            for key, value in zip(
                MainCategoryItem.objects.values_list("main_category__name", flat=True),
                MainCategoryItem.objects.values_list("color", flat=True),
            )
        }

        # Update all dependent dates in items
        update_all_dependent_dates()

        completed_state = self.request.GET.get("completed_state")
        sort_by_date_state = self.request.GET.get("sort_by_date_state")
        filter_item_list = self.request.GET.get("filter_item_list")

        # Filter all todo items
        filtered_items = filter_item_lists_by_query(
            filter_item_list, self.model.objects.prefetch_related("tags")
        )

        queryset = filtered_items.filter(AT_LEAST_ONE_DATE_FIELD).order_by(
            Case(
                When(date_start_earliest__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=DateField(),
            ),
            "date_start_earliest",
            Case(
                When(date_start_latest__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=DateField(),
            ),
            "date_start_latest",
            Case(
                When(date_due__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=DateField(),
            ),
            "date_due",
            Case(
                When(sorting_priority__isnull=True, then=Value(1)),
                default=Value(0),
                output_field=FloatField(),
            ),
            "-sorting_priority",
            Case(
                When(title="", then=Value(1)),
                default=Value(0),
                output_field=CharField(),
            ),
            Lower("title"),
        )

        queryset = sort_by_date_state_filter(sort_by_date_state, queryset)

        queryset = completed_state_filter(completed_state, queryset)

        # Group by date
        items_grouped_by_date = {
            "Past": [],
            "Today": [],
            "Within 7 days": [],
            "Within 30 days": [],
            "Later": [],
        }
        for item in queryset:
            if (
                date_is_past(item.date_start_earliest, today)
                or date_is_past(item.date_start_latest, today)
                or date_is_past(item.date_due, today)
            ):
                items_grouped_by_date["Past"].append(item)
            elif (
                date_is_today(item.date_start_earliest, today)
                or date_is_today(item.date_start_latest, today)
                or date_is_today(item.date_due, today)
            ):
                items_grouped_by_date["Today"].append(item)
            elif (
                date_is_within_dates(
                    item.date_start_earliest,
                    start_date=today + timedelta(days=1),
                    end_date=today + timedelta(days=7),
                )
                or date_is_within_dates(
                    item.date_start_latest,
                    start_date=today + timedelta(days=1),
                    end_date=today + timedelta(days=7),
                )
                or date_is_within_dates(
                    item.date_due,
                    start_date=today + timedelta(days=1),
                    end_date=today + timedelta(days=7),
                )
            ):
                items_grouped_by_date["Within 7 days"].append(item)
            elif (
                date_is_within_dates(
                    item.date_start_earliest,
                    start_date=today + timedelta(days=8),
                    end_date=today + timedelta(days=30),
                )
                or date_is_within_dates(
                    item.date_start_latest,
                    start_date=today + timedelta(days=8),
                    end_date=today + timedelta(days=30),
                )
                or date_is_within_dates(
                    item.date_due,
                    start_date=today + timedelta(days=8),
                    end_date=today + timedelta(days=30),
                )
            ):
                items_grouped_by_date["Within 30 days"].append(item)
            else:
                items_grouped_by_date["Later"].append(item)

        context["items_grouped_by_date"] = items_grouped_by_date

        return context


class TodoItemListView(ListView):
    model = ToDoItem
    template_name = "taskmanager_app/todo_list_view.html"

    def get_queryset(self):
        # Update all dependent dates in items
        update_all_dependent_dates()

        completed_state = self.request.GET.get("completed_state")
        dates_state = self.request.GET.get("dates_state")
        filter_item_list = self.request.GET.get("filter_item_list")

        # Filter all todo items
        filtered_items = filter_item_lists_by_query(
            filter_item_list, self.model.objects.prefetch_related("tags")
        )

        filtered_items = dates_state_filter(dates_state, filtered_items)
        return completed_state_filter(completed_state, filtered_items)

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        context["main_categories"] = {
            key: value
            for key, value in zip(
                MainCategoryItem.objects.values_list("main_category__name", flat=True),
                MainCategoryItem.objects.values_list("color", flat=True),
            )
        }
        return context


class TodoItemTableView(View):
    model = ToDoItem
    template_name = "taskmanager_app/todo_table_view.html"

    def get(self, request):
        # Update all dependent dates in items
        update_all_dependent_dates()

        items = self.model.objects.all()
        sort_by = request.GET.get("sort_by")
        sort_order = request.GET.get("sort_order")
        filter_title = request.GET.get("filter_title")
        filter_tags = request.GET.get("filter_tags")
        completed_state = request.GET.get("completed_state")
        dates_state = request.GET.get("dates_state")

        items = completed_state_filter(completed_state, items)
        items = dates_state_filter(dates_state, items)

        # Handle filtering by title query
        if filter_title:
            # Split the query into individual words
            query_words = filter_title.split() if filter_title else [""]

            # Filter cases that include all the words in title
            items = items.filter(Q(title__icontains=query_words[0])).distinct()
            for word in query_words[1:]:
                items = items.filter(Q(title__icontains=word)).distinct()

        # Handle filtering by tags query
        if filter_tags:
            # Split the query into individual words
            query_words = filter_tags.split() if filter_tags else [""]

            # Filter cases that include all the words in tags
            items = items.filter(Q(tags__name__icontains=query_words[0])).distinct()
            for word in query_words[1:]:
                items = items.filter(Q(tags__name__icontains=word)).distinct()

        # Handle sorting
        if sort_by:
            if sort_order == "desc":
                sort_by = f"-{sort_by}"
                sort_order = "asc"
            else:
                sort_order = "desc"
            items = items.order_by(sort_by)
        else:
            sort_order = "asc"

        # Replace None values with empty strings
        items = self.replace_none_with_empty_strings(items)

        context = {
            "items": items,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "filter_title": filter_title,
            "filter_tags": filter_tags,
            "completed_state": completed_state,
            "dates_state": dates_state,
        }
        return render(request, self.template_name, context)

    @staticmethod
    def replace_none_with_empty_strings(items):
        for item in items:
            for field in item._meta.fields:
                if getattr(item, field.name) is None:
                    setattr(item, field.name, "-")
        return items


class TodoItemCreate(CreateView):
    model = ToDoItem
    form_class = ToDoItemForm
    template_name = "taskmanager_app/todoitem_form.html"

    def get_context_data(self, **kwargs):
        context = super(TodoItemCreate, self).get_context_data(**kwargs)
        context["title"] = "Create a new item"
        return context

    def form_valid(self, form):
        # Custom validation for title
        title = form.cleaned_data["title"]

        # Check title being unique
        if self.model.objects.filter(title=title).exists():
            form.add_error(
                "title",
                "*Title already exists. Please select another title.",
            )
            return self.form_invalid(form)

        # Check if title is empty
        if not title:
            form.add_error(
                "title",
                "*Title cannot be empty. Please enter a title.",
            )
            return self.render_to_response(self.get_context_data(form=form))

        # Check dependency chain
        ### NO check of date dependencies, as a newly created item ALWAYS will be in the end of the chain, hence, cannot break it

        return super().form_valid(form)

    def get_success_url(self):
        # Update all dependent dates in items
        update_all_dependent_dates()

        return reverse_lazy("index")


class TodoItemEdit(UpdateView):
    model = ToDoItem
    form_class = ToDoItemForm
    template_name = "taskmanager_app/todoitem_form.html"

    def get_context_data(self, **kwargs):
        context = super(TodoItemEdit, self).get_context_data(**kwargs)
        context["title"] = "Edit item"
        return context

    def form_valid(self, form):
        # Custom validation for title
        title = form.cleaned_data["title"]

        # Check title being unique
        if self.model.objects.exclude(pk=self.object.pk).filter(title=title).exists():
            form.add_error(
                "title",
                "*Title already exists. Please select another title.",
            )
            return self.form_invalid(form)

        # Check if title is empty
        if not title:
            form.add_error(
                "title",
                "*Title cannot be empty. Please enter a title.",
            )
            return self.form_invalid(form)

        # Check dependency chain
        _, error_flag, form = get_date_dependency_chain(
            return_error_msg=True, form=form, item_id=self.kwargs["pk"]
        )
        if error_flag:
            return self.form_invalid(form)

        return super().form_valid(form)

    def get_success_url(self):
        # Update all dependent dates in items
        update_all_dependent_dates()

        # Get the previously visited page URL from the session
        previous_url = self.request.session.get("previous_url")

        if previous_url:
            return previous_url

        # If there is no previous URL in the session, use a fallback URL
        return reverse_lazy("index")

    def get(self, request, *args, **kwargs):
        # Store the current page's URL as the previous URL in the session
        self.request.session["previous_url"] = self.request.META.get("HTTP_REFERER")

        return super().get(request, *args, **kwargs)


class TodoItemDelete(DeleteView):
    model = ToDoItem

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context

    def get_success_url(self):
        return reverse_lazy("index")


class TodoItemCopy(View):
    model = ToDoItem
    form_class = ToDoItemForm

    def post(self, request, *args, **kwargs):
        item_id = self.kwargs["pk"]
        original_item = self.model.objects.get(pk=item_id)

        # Creates new temporary unique title
        new_title_base = f"COPY OF: {original_item.title}"
        new_title = new_title_base
        count = 1

        while ToDoItem.objects.filter(title=new_title).exists():
            new_title = f"{new_title_base}{count}"
            count += 1

        # Creates new item based on original
        new_item = ToDoItem.objects.create(
            title=new_title,
            description=original_item.description,
            # tags=original_item.tags.all(),
            completed=original_item.completed,
            date_start_earliest=original_item.date_start_earliest,
            date_start_latest=original_item.date_start_latest,
            date_due=original_item.date_due,
            date_start_earliest_depend=original_item.date_start_earliest_depend,
            date_start_latest_depend=original_item.date_start_latest_depend,
            date_due_depend=original_item.date_due_depend,
            date_start_earliest_depend_id=original_item.date_start_earliest_depend_id,
            date_start_latest_depend_id=original_item.date_start_latest_depend_id,
            date_due_depend_id=original_item.date_due_depend_id,
            date_start_earliest_depend_type=original_item.date_start_earliest_depend_type,
            date_start_latest_depend_type=original_item.date_start_latest_depend_type,
            date_due_depend_type=original_item.date_due_depend_type,
            date_start_earliest_depend_shift=original_item.date_start_earliest_depend_shift,
            date_start_latest_depend_shift=original_item.date_start_latest_depend_shift,
            date_due_depend_shift=original_item.date_due_depend_shift,
            sorting_priority=original_item.sorting_priority,
        )

        # Copy the tags from the original item to the new item
        for tag in original_item.tags.all():
            new_item.tags.add(tag)

        return redirect(
            "item-edit", pk=new_item.pk
        )  # Redirect to the edit page of the new item


class MainCategoryListView(ListView):
    model = MainCategoryItem
    template_name = "taskmanager_app/maincategory_list_view.html"

    def get_queryset(self):
        return self.model.objects.prefetch_related("main_category").all()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return context


class MainCategoryItemCreate(CreateView):
    model = MainCategoryItem
    form_class = MainCategoryItemEditForm
    template_name = "taskmanager_app/maincategoryitem_form.html"

    def get_context_data(self, **kwargs):
        context = super(MainCategoryItemCreate, self).get_context_data(**kwargs)
        context["title"] = "Create a new main category item"
        return context

    def form_valid(self, form):
        # Custom validation for unique main_category
        main_category = form.cleaned_data["main_category"][0]
        if len(form.cleaned_data["main_category"]) > 1:
            form.add_error(
                "main_category",
                "*Main category can maximum contain one tag.",
            )
            return self.form_invalid(form)

        if main_category.lower() == "other":
            form.add_error(
                "main_category",
                "*Main category is not allowed to be 'Other'. Please select another category.",
            )
            return self.form_invalid(form)

        if MainCategoryItem.objects.filter(main_category__name=main_category).exists():
            form.add_error(
                "main_category",
                "*Main category already exists. Please select another category.",
            )
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("index")


class MainCategoryItemEdit(UpdateView):
    model = MainCategoryItem
    form_class = MainCategoryItemEditForm
    template_name = "taskmanager_app/maincategoryitem_form.html"

    def get_object(self):
        main_category_name = self.kwargs.get("pk", None)
        return get_object_or_404(
            MainCategoryItem, main_category__name__iexact=main_category_name
        )

    def get_context_data(self, **kwargs):
        context = super(MainCategoryItemEdit, self).get_context_data(**kwargs)
        context["title"] = "Edit main category item"
        context["url_id"] = self.object.main_category.first().name
        return context

    def form_valid(self, form):
        # Custom validation for unique main_category
        main_category = form.cleaned_data["main_category"][0]
        if len(form.cleaned_data["main_category"]) > 1:
            form.add_error(
                "main_category",
                "*Main category can maximum contain one tag.",
            )
            return self.form_invalid(form)

        if main_category.lower() == "other":
            form.add_error(
                "main_category",
                "*Main category is not allowed to be 'Other'. Please select another category.",
            )
            return self.form_invalid(form)

        if (
            MainCategoryItem.objects.exclude(pk=self.object.pk)
            .filter(main_category__name=main_category)
            .exists()
        ):
            form.add_error(
                "main_category",
                "*Main category already exists. Please select another category.",
            )
            return self.form_invalid(form)
        return super().form_valid(form)

    def get_success_url(self):
        # Get the previously visited page URL from the session
        previous_url = self.request.session.get("previous_url")

        if previous_url:
            return previous_url

        # If there is no previous URL in the session, use a fallback URL
        return reverse_lazy("index")

    def get(self, request, *args, **kwargs):
        # Store the current page's URL as the previous URL in the session
        self.request.session["previous_url"] = self.request.META.get("HTTP_REFERER")

        return super().get(request, *args, **kwargs)


class MainCategoryItemShow(DetailView):
    model = MainCategoryItem
    form_class = MainCategoryItemShowForm
    template_name = "taskmanager_app/maincategoryitem_show.html"

    def get_object(self):
        main_category_name = self.kwargs.get("pk", None)
        return get_object_or_404(
            MainCategoryItem, main_category__name__iexact=main_category_name
        )

    def get_context_data(self, **kwargs):
        context = super(MainCategoryItemShow, self).get_context_data(**kwargs)
        main_tag = self.object.main_category.first().name
        sub_category_tags = sorted(
            self.object.sub_categories.all(), key=lambda x: x.name
        )
        excluded_tags = sorted(self.object.excluded_tags.all(), key=lambda x: x.name)
        completed_state = self.request.GET.get("completed_state")
        dates_state = self.request.GET.get("dates_state")
        filter_item_list = self.request.GET.get("filter_item_list")
        color = self.object.color

        context["title"] = main_tag
        context["sub_category_tags"] = sub_category_tags
        context["excluded_tags"] = excluded_tags
        context["background_color"] = color

        # Get main category text field from text_field_from_item
        if item_id := self.object.text_field_from_item:
            if ToDoItem.objects.filter(id=item_id).exists():
                todo_item = ToDoItem.objects.get(id=item_id)
                context["description_field"] = todo_item.description

        # Update all dependent dates in items
        update_all_dependent_dates()

        # Filter all todo items
        filtered_items = filter_item_lists_by_query(
            filter_item_list, ToDoItem.objects.prefetch_related("tags")
        )

        sorted_grouped_todo_items = get_sorted_grouped_todo_items(
            filtered_items=filtered_items,
            main_tag=main_tag,
            sub_category_tags=sub_category_tags,
            excluded_tags=excluded_tags,
            completed_state=completed_state,
            dates_state=dates_state,
        )

        context["grouped_todo_items"] = sorted_grouped_todo_items

        main_categories = self.model.objects.values_list(
            "main_category__name", flat=True
        )
        context["main_category_links"] = {item: True for item in main_categories}
        context["main_categories"] = {
            key: value
            for key, value in zip(
                MainCategoryItem.objects.values_list("main_category__name", flat=True),
                MainCategoryItem.objects.values_list("color", flat=True),
            )
        }
        return context

    def get_success_url(self):
        return reverse_lazy("index")


class MainCategoryItemDelete(DeleteView):
    model = MainCategoryItem

    def get_object(self):
        main_category_name = self.kwargs.get("pk", None)
        return get_object_or_404(
            MainCategoryItem, main_category__name__iexact=main_category_name
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["title"] = self.object.main_category.first().name
        return context

    def get_success_url(self):
        return reverse_lazy("index")


class MainCategoryItemShowAll(ListView):
    model = MainCategoryItem
    form_class = MainCategoryItemShowForm
    template_name = "taskmanager_app/maincategoryitem_show_all.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data()
        main_categories = self.model.objects.prefetch_related(
            "main_category", "sub_categories", "excluded_tags"
        ).all()
        main_category_names = list(
            main_categories.values_list("main_category__name", flat=True)
        )
        completed_state = self.request.GET.get("completed_state")
        dates_state = self.request.GET.get("dates_state")
        filter_item_list = self.request.GET.get("filter_item_list")

        # Update all dependent dates in items
        update_all_dependent_dates()

        # Filter all todo items
        filtered_items = filter_item_lists_by_query(
            filter_item_list, ToDoItem.objects.prefetch_related("tags")
        )
        state_filtered_todo_items = completed_state_filter(
            completed_state,
            filtered_items.order_by("-sorting_priority", "title"),
        )
        state_filtered_todo_items = dates_state_filter(
            dates_state,
            state_filtered_todo_items,
        )

        all_grouped_todo_items = {}
        main_category_links = {}
        for main_category, main_category_name in zip(
            main_categories, main_category_names
        ):
            sub_category_tags = sorted(
                main_category.sub_categories.all(),
                key=lambda x: x.name,
            )
            excluded_tags = sorted(
                main_category.excluded_tags.all(),
                key=lambda x: x.name,
            )

            main_category_links[main_category_name] = True
            sorted_grouped_todo_items = get_sorted_grouped_todo_items(
                filtered_items=state_filtered_todo_items,
                main_tag=main_category_name,
                sub_category_tags=sub_category_tags,
                excluded_tags=excluded_tags,
                completed_state=completed_state,
                dates_state=dates_state,
            )

            if sorted_grouped_todo_items:
                all_grouped_todo_items[main_category_name] = dict(
                    sorted_grouped_todo_items
                )

        # Identify todo items without any main category
        items_without_main_tags = []
        for item in state_filtered_todo_items:
            item_tags = [tag.name for tag in item.tags.all()]
            if all(tag not in item_tags for tag in main_category_names):
                items_without_main_tags.append(item)
        if items_without_main_tags:
            all_grouped_todo_items["Other"] = {}
            all_grouped_todo_items["Other"][""] = items_without_main_tags

        context["all_grouped_todo_items"] = dict(all_grouped_todo_items)
        context["main_category_links"] = {item: True for item in main_category_names}
        context["main_categories"] = {
            key: value
            for key, value in zip(
                main_category_names,
                MainCategoryItem.objects.values_list("color", flat=True),
            )
        }

        return context

    def get_success_url(self):
        return reverse_lazy("index")


def markdown_db_uploader(request):
    """
    Makdown image upload for dropbox storage
    and represent as json to markdown editor.
    """
    if (
        request.method == "POST"
        and request.META.get("HTTP_X_REQUESTED_WITH") == "XMLHttpRequest"
    ):
        if "markdown-image-upload" in request.FILES:
            image = request.FILES["markdown-image-upload"]
            image_types = [
                "image/png",
                "image/jpg",
                "image/jpeg",
                "image/pjpeg",
                "image/gif",
            ]
            if image.content_type not in image_types:
                data = json.dumps(
                    {"status": 405, "error": _("Bad image format.")}, cls=LazyEncoder
                )
                return HttpResponse(data, content_type="application/json", status=405)

            if image.size > settings.MAX_IMAGE_UPLOAD_SIZE:
                to_MB = settings.MAX_IMAGE_UPLOAD_SIZE / (1024 * 1024)
                data = json.dumps(
                    {
                        "status": 405,
                        "error": _("Maximum image file is %(size)s MB.")
                        % {"size": to_MB},
                    },
                    cls=LazyEncoder,
                )
                return HttpResponse(data, content_type="application/json", status=405)

            img_uuid = "{0}-{1}".format(
                uuid.uuid4().hex[:10], image.name.replace(" ", "-")
            )

            # dbx = dropbox.Dropbox(settings.DROPBOX_OAUTH2_TOKEN)
            dbx = dropbox.Dropbox(
                app_key=settings.DROPBOX_APP_KEY,
                app_secret=settings.DROPBOX_APP_SECRET,
                oauth2_refresh_token=settings.DROPBOX_OAUTH2_REFRESH_TOKEN,
            )
            with image.open() as f:
                dbx.files_upload(f.read(), f"/{img_uuid}")

            # Attemptin to fetch shared_link while waiting for dropbox server image upload
            attempts = 0
            while attempts < MAX_ATTEMPTS:
                try:
                    dbx_link = dbx.sharing_create_shared_link(
                        f"/{img_uuid}", short_url=True
                    )
                    img_url = (
                        dbx_link.url.replace("?dl=0", "").replace("&dl=0", "") + "&dl=1"
                    )
                    attempts = MAX_ATTEMPTS + 1
                except exceptions.ApiError:
                    attempts += 1
                    img_url = "failed_to_fetch_shared_link_to_dropbox"
                    print("Attempt " + str(attempts) + " to fetch shared link")
                    time.sleep(1)

            data = json.dumps({"status": 200, "link": img_url, "name": image.name})
            return HttpResponse(data, content_type="application/json")
        return HttpResponse(_("Invalid request!"))
    return HttpResponse(_("Invalid request!"))
