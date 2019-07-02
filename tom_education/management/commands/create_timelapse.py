import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from tom_dataproducts.models import DataProductGroup
from tom_targets.models import Target

from tom_education.models import TimelapseDataProduct
from tom_education.tasks import make_timelapse


# Supress imageio warnings
logging.getLogger("imageio").setLevel(logging.CRITICAL)


class Command(BaseCommand):
    RAW_FILE_EXTENSION = 'e91.fits.fz'

    help = 'Create a timelapse from a series of data products for a target'

    def add_arguments(self, parser):
        parser.add_argument('target_pk', type=int)

    def handle(self, *args, **options):
        # Get the tagret
        target_pk = options['target_pk']
        try:
            target = Target.objects.get(pk=target_pk)
        except Target.DoesNotExist:
            raise CommandError('Target \'{}\' does not exist'.format(target_pk))

        # Get the 'good quality' group
        group_name = getattr(settings, 'TOM_EDUCATION_TIMELAPSE_GROUP_NAME', 'Timelapse quality')
        try:
            group, _ = DataProductGroup.objects.get_or_create(name=group_name)
        except DataProductGroup.MultipleObjectsReturned:
            raise CommandError(
                'Multiple data products groups found with name \'{}\''.format(group_name)
            )

        prods = group.dataproduct_set.filter(target=target).exclude(data__endswith=self.RAW_FILE_EXTENSION)
        self.stdout.write('Creating timelapse of {n} files for target {ident} ({name})...'.format(
            n=prods.count(),
            ident=target.identifier,
            name=target.name
        ))

        if not prods.exists():
            self.stdout.write('Nothing to do')
            return

        tl = TimelapseDataProduct.create_timestamped(target, prods)
        make_timelapse(tl.pk)
        self.stdout.write(self.style.SUCCESS('Created timelapse {}'.format(tl.data.path)))
