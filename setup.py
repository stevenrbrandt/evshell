from setuptools import setup, find_packages
from pieshell.version import __version__

setup(
  name='Pieshell',
  version=__version__,
  description='An implementation of the shell in pure Python',
  long_description='An implementation of the shell in pure Python',
  url='https://github.com/stevenrbrandt/pieshell.git',
  author='Steven R. Brandt',
  author_email='steven@stevenrbrandt.com',
  license='LGPL',
  packages=['pieshell'],
  entry_points = {
    'console_scripts' : ['pieshell=pieshell:main'],
  },
  install_requires=['piraha']
)
