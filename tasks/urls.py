from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('queuei/', views.run_task, name='queuei'),
]