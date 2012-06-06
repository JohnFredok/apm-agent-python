#!/usr/bin/env python
"""
opbeat_python
======

opbeat_python is a Python client for `Opbeat <https://opbeat.com/>`_. It provides
full out-of-the-box support for many of the popular frameworks, including
`Django <djangoproject.com>`_, `Flask <http://flask.pocoo.org/>`_, and `Pylons
<http://www.pylonsproject.org/>`_. opbeat_python also includes drop-in support for any
`WSGI <http://wsgi.readthedocs.org/>`_-compatible web application.
"""

# Hack to prevent stupid "TypeError: 'NoneType' object is not callable" error
# in multiprocessing/util.py _exit_function when running `python
# setup.py test` (see
# http://www.eby-sarna.com/pipermail/peak/2010-May/003357.html)
try:
    import multiprocessing
except ImportError:
    pass

from setuptools import setup, find_packages

tests_require = [
    'blinker>=1.1',
    'celery',
    'Django>=1.2,<1.4',
    'django-celery',
    'django-nose',
    'gevent',
    'Flask>=0.8',
    'logbook',
    'nose',
    'mock',
    'pep8',
    'sentry>=4.4.6',
    'unittest2',
    'webob',
    'zerorpc>=0.2.0',
    'pytz'
]

install_requires = [
    'simplejson>=2.3.0,<2.5.0',
]

setup(
    name='opbeat_python',
    version='1.0',
    author='Ron Cohen',
    author_email='ron@opbeat.com',
    url='http://github.com/opbeat/opbeat_python',
    description='opbeat_python is a client for Opbeat (https://www.opbeat.com)',
    long_description=__doc__,
    packages=find_packages(exclude=("tests",)),
    zip_safe=False,
    install_requires=install_requires,
    tests_require=tests_require,
    extras_require={'test': tests_require},
    test_suite='runtests.runtests',
    include_package_data=True,
    entry_points={
        'console_scripts': [
            'opbeat = opbeat_python.scripts.runner:main',
        ],
        'paste.filter_app_factory': [
            'opbeat_python = opbeat_python.contrib.paste:sentry_filter_factory',
        ],
    },
    classifiers=[
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Topic :: Software Development'
    ],
)
