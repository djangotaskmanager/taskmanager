from django.contrib import admin
from django.db import models
from martor.widgets import AdminMartorWidget
from taskmanager_app.models import ToDoItem, MainCategoryItem


class YourModelAdmin(admin.ModelAdmin):
    formfield_overrides = {
        models.TextField: {"widget": AdminMartorWidget},
    }


admin.site.register(ToDoItem, YourModelAdmin)
admin.site.register(MainCategoryItem)
