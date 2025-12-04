from django.urls import path, include
from taskmanager_app import views

urlpatterns = [
    path("", views.MainCategoryListView.as_view(), name="index"),
    path("search/", views.SearchResultsView.as_view(), name="search_results"),
    path("todo-list-view/", views.TodoItemListView.as_view(), name="todo_list_view"),
    path("todo-table-view/", views.TodoItemTableView.as_view(), name="todo_table_view"),
    # CRUD patterns for ToDoItems
    path(
        "item/add/",
        views.TodoItemCreate.as_view(),
        name="item-add",
    ),
    path(
        "item/<int:pk>/",
        views.TodoItemEdit.as_view(),
        name="item-edit",
    ),
    path("item/<str:title>/", views.edit_item_by_title, name="edit-item-by-title"),
    path(
        "item/<int:pk>/delete/",
        views.TodoItemDelete.as_view(),
        name="item-delete",
    ),
    path("item/<int:pk>/copy/", views.TodoItemCopy.as_view(), name="item-copy"),
    # CRUD patterns for MainCategoryItem
    path(
        "main_category/add/",
        views.MainCategoryItemCreate.as_view(),
        name="main_category-add",
    ),
    path(
        "main_category/<str:pk>/",
        views.MainCategoryItemShow.as_view(),
        name="main_category-show",
    ),
    path(
        "main_category/<str:pk>/edit/",
        views.MainCategoryItemEdit.as_view(),
        name="main_category-edit",
    ),
    path(
        "main_category/<str:pk>/delete/",
        views.MainCategoryItemDelete.as_view(),
        name="main_category-delete",
    ),
    path(
        "main_category_all/",
        views.MainCategoryItemShowAll.as_view(),
        name="main_category-show-all",
    ),
    path(
        "sorting_view/",
        views.SortingView.as_view(),
        name="sorting_view",
    ),
    path("autocomplete_titles/", views.autocomplete_titles, name="autocomplete_titles"),
    path("api/uploader/", views.markdown_db_uploader, name="markdown_uploader_page"),
    path("taggit/", include("taggit_selectize.urls")),
]
