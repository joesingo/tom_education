from django.urls import path

from tom_education.views import (
    ActionableTargetDetailView,
    AsyncStatusApi,
    AutovarProcessApi,
    AutovarProcessDetailView,
    GalleryView,
    TemplatedObservationCreateView,
)

app_name = "tom_education"

urlpatterns = [
    path('observations/<str:facility>/create/', TemplatedObservationCreateView.as_view(), name='create_obs'),
    path('targets/<int:pk>/', ActionableTargetDetailView.as_view(), name='target_detail'),
    path('async/status/<target>/', AsyncStatusApi.as_view(), name='async_process_status_api'),
    path('autovar/<pk>', AutovarProcessDetailView.as_view(), name='autovar_detail'),
    path('autovar/logs/<pk>', AutovarProcessApi.as_view(), name='autovar_api'),
    path('gallery/', GalleryView.as_view(), name='gallery'),
]
