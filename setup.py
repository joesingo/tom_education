from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='tom_education',
    version='0.1.0',
    description='TOM toolkit plugin for educational projects',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Joe Singleton',
    author_email='joesingo@gmail.com',
    maintainer='Edward Gomez',
    maintainer_email='egomez@lco.global',
    install_requires=[
        'astroscrappy==1.0.8',
        'tomtoolkit @ git+https://github.com/TOMToolkit/tom_base.git@development#egg=tomtoolkit',
        'numpy',
        'imageio-ffmpeg==0.3.0',
        'imageio==2.5.0',
        'django-dramatiq==0.7.1',
        'dramatiq==1.6.0',
        'redis==3.2.1',
        'watchdog==0.9.0',
        'watchdog-gevent==0.1.1',
        'djangorestframework==3.10.1',
    ],
    packages=find_packages(),
    include_package_data=True,
    extras_require={
        'test': ['factory_boy', 'rise-set']
    }
)
