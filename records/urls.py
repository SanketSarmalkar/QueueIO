from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('', views.dashboard, name='dashboard'),
    path('records/', views.get_more_records, name='get_more_records'),
    path('get-report/<str:report_id>/', views.get_report_content, name='get_report_content'),
    path('intel-chat/', views.intel_chat_view, name='intel_chat'),
    path('command-center/', views.command_center_view, name='command_center'),
    path('nexus-data/', views.get_nexus_graph, name='nexus_data'),
    path('settings/', views.settings_view, name='settings'),
    path('cron/', views.cron_manager_view, name='cron_manager'),
]