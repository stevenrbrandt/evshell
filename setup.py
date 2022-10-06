from setuptools import setup, find_packages

setup(
  name='Pieshell',
  version='0.0.1',
  description='An implementation of the shell in pure Python',
  long_description='An implementation of the shell in pure Python',
  url='https://github.com/stevenrbrandt/pieshell.git',
  author='Steven R. Brandt',
  author_email='steven@stevenrbrandt.com',
  license='LGPL',
  packages=['pieshell'],
  install_requires=['piraha']
)
