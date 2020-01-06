from django import forms
from django.contrib import admin

from tom_education.models import ObservationTemplate, PipelineProcess
from tom_dataproducts.models import DataProduct


@admin.register(ObservationTemplate)
class ObservationTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'target', 'facility')


class DataProductAdminForm(forms.ModelForm):
    class Meta:
        model = DataProduct
        fields = '__all__'
        widgets = {
            'data_product_type': forms.Textarea(attrs={'cols': 98})
        }


class DataProductAdmin(admin.ModelAdmin):
    form = DataProductAdminForm

admin.site.register(PipelineProcess)
