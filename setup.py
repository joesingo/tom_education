from setuptools import setup, find_packages
from os import path

here = path.abspath(path.dirname(__file__))
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='tom_education',
    version='0.0.1',
    description='Plugin for the TOM toolkit',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Joe Singleton',
    author_email='joesingo@gmail.com',
    install_requires=[
        'tomtoolkit',
        'imageio-ffmpeg==0.3.0',
        'imageio @ git+https://github.com/imageio/imageio@7d49d41d6400704e2b33ca858343e7c04a940559',
    ],
    packages=find_packages(),
    include_package_data=True,
)
