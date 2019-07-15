from django.urls import path

from tom_education.views import (
    ActionableTargetDetailView,
    AsyncStatusApi,
    GalleryView,
    PipelineProcessApi,
    PipelineProcessDetailView,
    TemplatedObservationCreateView,
)

app_name = "tom_education"

urlpatterns = [
    path('observations/<str:facility>/create/', TemplatedObservationCreateView.as_view(), name='create_obs'),
    path('targets/<int:pk>/', ActionableTargetDetailView.as_view(), name='target_detail'),
    path('async/status/<target>/', AsyncStatusApi.as_view(), name='async_process_status_api'),
    path('pipeline/<pk>', PipelineProcessDetailView.as_view(), name='pipeline_detail'),
    path('pipeline/logs/<pk>', PipelineProcessApi.as_view(), name='pipeline_api'),
    path('gallery/', GalleryView.as_view(), name='gallery'),
]
