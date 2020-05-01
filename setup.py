from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='tom_education',
    version='1.1.6',
    description='TOM toolkit plugin for educational projects',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Joe Singleton',
    author_email='joesingo@gmail.com',
    maintainer='Edward Gomez',
    maintainer_email='egomez@lco.global',
    install_requires=[
        'astropy',
        'astroscrappy',
        'tomtoolkit>=1.4.0',
        'numpy',
        'imageio-ffmpeg',
        'imageio',
        'django-dramatiq',
        'dramatiq',
        'redis',
        'watchdog',
        'watchdog-gevent',
        'djangorestframework',
        'fits2image==0.4.3',
        'django-storages',
        'boto3',
    ],
    packages=find_packages(),
    include_package_data=True,
    extras_require={
        'test': ['factory_boy']
    }
)
