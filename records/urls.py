from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='login.html'), name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('signup/', views.signup_view, name='signup'),
    path('', views.dashboard, name='dashboard'),
    path('records/', views.get_more_records, name='get_more_records'),
    path('search/', views.search_records, name='search_records'),
    path('related/<str:report_id>/', views.get_related_reports, name='get_related_reports'),
    path('bookmarks/', views.list_bookmarks, name='list_bookmarks'),
    path('bookmark/', views.toggle_bookmark, name='toggle_bookmark'),
    path('get-report/<str:report_id>/', views.get_report_content, name='get_report_content'),
    path('intel-chat/', views.intel_chat_view, name='intel_chat'),
    path('command-center/', views.command_center_view, name='command_center'),
    path('nexus-data/', views.get_nexus_graph, name='nexus_data'),
    path('settings/', views.settings_view, name='settings'),
    path('cron/', views.cron_manager_view, name='cron_manager'),
    path('doc/', views.docs_view, name='docs'),
    path('docs/', views.docs_view, name='docs_alias'),
    path('entity-stats/', views.get_entity_stats, name='entity_stats'),
    path('usage-stats/', views.get_usage_stats, name='usage_stats'),
    path('stocks-data/', views.get_stocks_data, name='stocks_data'),
]