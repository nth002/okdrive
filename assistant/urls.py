from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/status/', views.get_status, name='get_status'),
    path('api/process-audio/', views.process_audio, name='process_audio'),
    path('api/process-command/', views.process_command, name='process_command'),
    path('api/latency/', views.get_latency, name='get_latency'),
    path('api/debug/', views.debug_responses, name='debug_responses'),  # Optional
]