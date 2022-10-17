from setuptools import setup, find_packages
import re

vfile="evshell/version.py"
verstrline = open(vfile, "rt").read()
VSRE = r"^__version__\s*=\s*(['\"])(.*)\1"
g = re.search(VSRE, verstrline, re.M)
if g:
    __version__ = g.group(2)
else:
    raise RuntimeError(f"Unable to find version in file '{vfile}")

setup(
  name='evshell',
  version=__version__,
  description='evshell: The Everglades Shell, an implementation of the shell in pure Python',
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
