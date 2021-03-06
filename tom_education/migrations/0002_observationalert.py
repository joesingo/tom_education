# Generated by Django 2.2.2 on 2019-07-30 15:46

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tom_observations', '0003_auto_20190503_2318'),
        ('tom_education', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='ObservationAlert',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('observation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='tom_observations.ObservationRecord')),
            ],
        ),
    ]
