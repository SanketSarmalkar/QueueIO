from django.urls import path
from django.contrib.auth import views as auth_views
from . import views
from .script_custom import migrate, backfill_entity

urlpatterns = [
    path('queuei/<str:task_key>/', views.run_task, name='run_generic_task'),
    path('alert/', views.slack_alert, name='slack_alert'),
    path("playlist_fix/", migrate.backfill_playlist_data),
    path("backfill_entities/", backfill_entity.backfill_entities),
]