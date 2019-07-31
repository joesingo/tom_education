from django.db import models

from tom_observations.models import ObservationRecord


class ObservationAlert(models.Model):
    """
    A model to store an email address with an observation, so that an alert can
    be issued when there is a change in the observation status
    """
    observation = models.ForeignKey(ObservationRecord, on_delete=models.CASCADE)
    email = models.EmailField()
