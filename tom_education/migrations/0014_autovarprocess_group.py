# Generated by Django 2.2.2 on 2019-07-15 09:48

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tom_dataproducts', '0005_auto_20190704_1010'),
        ('tom_education', '0013_auto_20190712_1137'),
    ]

    operations = [
        migrations.AddField(
            model_name='autovarprocess',
            name='group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='tom_dataproducts.DataProductGroup'),
        ),
    ]