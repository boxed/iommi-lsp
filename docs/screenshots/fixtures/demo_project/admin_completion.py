from django.contrib import admin

from myapp.models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    pass
