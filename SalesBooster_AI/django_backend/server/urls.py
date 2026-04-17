from django.contrib import admin
from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView
from core import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health', views.health_view),
    path('api/register', views.register_view),
    path('api/login', TokenObtainPairView.as_view()),
    path('api/keyword-search', views.keyword_search_view),
    path('api/keyword-search/', views.keyword_search_view),
    path('api/scrape-url', views.single_url_scrape_view),
    path('api/audit', views.api_audit_view),
    path('api/leads', views.list_leads_view),
    path('api/leads/import-csv', views.import_leads_csv_view),
    path('api/leads/<int:lead_id>/status', views.update_lead_status_view),
    path('api/analytics', views.campaign_analytics_view),
    path('api/send-bulk', views.send_bulk_view),
    path('api/smtp-status', views.smtp_status_view),
    path('api/followups/run', views.run_scheduled_followups_view),
    path('api/tasks', views.list_tasks_view),
    path('api/tasks/create-multichannel', views.create_tasks_for_nonresponders_view),
    path('api/tasks/<int:task_id>/complete', views.complete_task_view),
]
