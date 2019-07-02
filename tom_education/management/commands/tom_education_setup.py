"""
Script to write settings.py and urls.py for tom_education.

Should be run after setting up a TOM using the tom_setup script.
"""
import os.path
import sys

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.template.loader import get_template


class Command(BaseCommand):
    help = 'Create settings.py and urls.py for tom_education'

    project_name = os.path.basename(settings.BASE_DIR)

    def get_source_file_path(self, name):
        return os.path.join(settings.BASE_DIR, self.project_name, name)

    def ok(self):
        self.stdout.write(self.style.SUCCESS('OK'))

    def status(self, msg):
        self.stdout.write(msg, ending='')
        sys.stdout.flush()

    def handle(self, *args, **options):
        context = {'project_name': self.project_name}
        rendered_settings = get_template('tom_education/settings.py.tmpl').render(context)
        rendered_urls = get_template('tom_education/urls.py.tmpl').render({})

        settings_path = self.get_source_file_path('settings.py')
        self.status('Writing settings to {}... '.format(settings_path))
        with open(settings_path, 'w') as settings_file:
            settings_file.write(rendered_settings)
        self.ok()

        urls_path = self.get_source_file_path('urls.py')
        self.status('Writing urls to {}... '.format(urls_path))
        with open(urls_path, 'w') as urls_file:
            urls_file.write(rendered_urls)
        self.ok()

        self.status('Running migrations... ')
        call_command('migrate', verbosity=0, interactive=False)
        self.ok()

        self.stdout.write(self.style.SUCCESS('Finished'))
