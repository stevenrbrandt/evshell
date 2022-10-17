from setuptools import setup, find_packages
from evshell.version import __version__

setup(
  name='Everglades Shell',
  version=__version__,
  description='An implementation of the shell in pure Python',
  long_description='An implementation of the shell in pure Python',
  url='https://github.com/stevenrbrandt/evshell.git',
  author='Steven R. Brandt',
  author_email='steven@stevenrbrandt.com',
  license='LGPL',
  packages=['evshell'],
  entry_points = {
    'console_scripts' : ['evshell=evshell:main'],
  },
  install_requires=['piraha']
)
