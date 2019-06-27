from django.urls import path

from tom_education.views import TemplatedObservationCreateView, TimelapseTargetDetailView, TimelapseStatusApiView

app_name = "tom_education"

urlpatterns = [
    path('observations/<str:facility>/create/', TemplatedObservationCreateView.as_view(), name='create_obs'),
    path('targets/<int:pk>/', TimelapseTargetDetailView.as_view(), name='target_detail'),
    path('timelapse/status/<target>/', TimelapseStatusApiView.as_view(), name='timelapse_status_api'),
]
