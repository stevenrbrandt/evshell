from setuptools import setup, find_packages
from pieshell.version import __version__

setup(
  name='Snake Shell',
  version=__version__,
  description='An implementation of the shell in pure Python',
  long_description='An implementation of the shell in pure Python',
  url='https://github.com/stevenrbrandt/sshell.git',
  author='Steven R. Brandt',
  author_email='steven@stevenrbrandt.com',
  license='LGPL',
  packages=['sshell'],
  entry_points = {
    'console_scripts' : ['sshell=sshell:main'],
  },
  install_requires=['piraha']
)
