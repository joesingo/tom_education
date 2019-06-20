from django.urls import path

from tom_education.views import TemplatedObservationCreateView, TimelapseTargetDetailView

app_name = "tom_education"

urlpatterns = [
    path('observations/<str:facility>/create/', TemplatedObservationCreateView.as_view(), name='create_obs'),
    path('targets/<pk>/', TimelapseTargetDetailView.as_view(), name='target_detail'),
]
