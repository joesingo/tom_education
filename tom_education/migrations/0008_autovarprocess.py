# Generated by Django 2.2.2 on 2019-07-10 16:49

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tom_dataproducts', '0005_auto_20190704_1010'),
        ('tom_education', '0007_auto_20190710_1607'),
    ]

    operations = [
        migrations.CreateModel(
            name='AutovarProcess',
            fields=[
                ('asyncprocess_ptr', models.OneToOneField(auto_created=True, on_delete=django.db.models.deletion.CASCADE, parent_link=True, primary_key=True, serialize=False, to='tom_education.AsyncProcess')),
                ('logs', models.TextField()),
                ('input_files', models.ManyToManyField(related_name='autovar', to='tom_dataproducts.DataProduct')),
            ],
            bases=('tom_education.asyncprocess',),
        ),
    ]