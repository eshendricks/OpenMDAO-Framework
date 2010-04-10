# pylint: disable-msg=F0401

import os,sys
from setuptools import setup, find_packages

here = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(here,
                                                 'src',
                                                 'openmdao',
                                                 'main')))

import releaseinfo
version = releaseinfo.__version__

setup(name='openmdao.main',
      version=version,
      description="OpenMDAO framework infrastructure",
      long_description="""\
""",
      classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Intended Audience :: Science/Research',
        'License :: OSI Approved',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2.6',
        'Topic :: Scientific/Engineering',
      ],
      keywords='optimization multidisciplinary multi-disciplinary analysis',
      author='',
      author_email='',
      url='http://openmdao.org',
      license='NASA Open Source Agreement 1.3',
      namespace_packages=["openmdao"],
      packages=find_packages('src'),
      package_dir={'': 'src'},
      include_package_data=True,
      test_suite='nose.collector',
      zip_safe=False,
      install_requires=[
          'setuptools',
          'pyparsing>=1.5.2',
          'numpy>=1.3.0',
          'PyYAML',
          'networkx==1.0.1',
          'Traits>=3.0',
          'virtualenv',
          'openmdao.units',
          'openmdao.util',
      ],
      entry_points = {
          "console_scripts": [
                "openmdao_build_docs=openmdao.util.build_docs:build_docs",
                "openmdao_docs=openmdao.util.build_docs:view_docs",
                "wing=openmdao.util.wingproj:run_wing",
              ],
          },
    )
