from django.urls import path
from django.contrib.auth import views as auth_views
from .script_custom import migrate, backfill_entity
from . import views

urlpatterns = [
    path('queuei/<str:task_key>/', views.run_task, name='run_generic_task'),
    path('alert/', views.slack_alert, name='slack_alert'),
    path("video/<str:video_id>/", views.video_page, name="video_page"),
    path("playlist_fix/", migrate.backfill_playlist_data),
    path("backfill_entities/", backfill_entity.backfill_entities),
]