from django.contrib import admin
from .models import TaskConfiguration, GlobalSetting, CronJob, DashboardFeed

admin.site.register(TaskConfiguration)
admin.site.register(GlobalSetting)


@admin.register(CronJob)
class CronJobAdmin(admin.ModelAdmin):
    list_display = ('name', 'job_type', 'cron_expression', 'is_active', 'last_run_at')
    list_filter = ('job_type', 'is_active')


@admin.register(DashboardFeed)
class DashboardFeedAdmin(admin.ModelAdmin):
    list_display = ('title', 'key', 'render_type', 'is_active', 'created_at')
    list_filter = ('render_type', 'is_active')
    prepopulated_fields = {'key': ('title',)}