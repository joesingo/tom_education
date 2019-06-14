from django.contrib import admin

from tom_education.models import ObservationTemplate

@admin.register(ObservationTemplate)
class ObservationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'target', 'facility')
