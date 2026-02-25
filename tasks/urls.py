from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('queuei/<str:task_key>/', views.run_task, name='run_generic_task'),
    path('alert/', views.slack_alert, name='slack_alert'),
]