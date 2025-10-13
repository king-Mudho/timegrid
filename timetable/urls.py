"""
URL patterns for timetable app.
"""
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('allocate/<int:class_id>/', views.allocate_teachers, name='allocate_teachers'),
    path('generate/', views.generate_timetable, name='generate_timetable'),
    path('master/', views.master_timetable, name='master_timetable'),
    path('teachers/', views.teacher_timetable, name='teacher_list'),
    path('teachers/<int:teacher_id>/', views.teacher_timetable, name='teacher_detail'),
    path('classes/', views.class_timetable, name='class_list'),
    path('classes/<int:class_id>/', views.class_timetable, name='class_detail'),
    path('rooms/', views.room_timetable, name='room_list'),
    path('rooms/<int:room_id>/', views.room_timetable, name='room_detail'),
    path('conflicts/', views.conflict_report, name='conflict_report'),
    path('api/update-entry/', views.update_entry, name='update_entry'),
    path('export/<str:format>/<str:view_type>/', views.export_view, name='export'),
    path('export/<str:format>/<str:view_type>/<int:object_id>/', views.export_view, name='export_with_id'),
]
