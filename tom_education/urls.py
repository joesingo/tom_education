from django.urls import path

from tom_education.views import (
    TemplatedObservationCreateView, ActionableTargetDetailView, TimelapseStatusApiView,
    GalleryView
)

app_name = "tom_education"

urlpatterns = [
    path('observations/<str:facility>/create/', TemplatedObservationCreateView.as_view(), name='create_obs'),
    path('targets/<int:pk>/', ActionableTargetDetailView.as_view(), name='target_detail'),
    path('timelapse/status/<target>/', TimelapseStatusApiView.as_view(), name='timelapse_status_api'),
    path('gallery/', GalleryView.as_view(), name='gallery'),
]
