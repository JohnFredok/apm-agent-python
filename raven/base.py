"""
raven.base
~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

from __future__ import absolute_import

import base64
import datetime
import logging
import sys
import time
import traceback
import urllib2
import uuid

import raven
from raven.conf import defaults
from raven.utils import json, varmap, get_versions, get_signature, get_auth_header
from raven.utils.encoding import transform, force_unicode, shorten
from raven.utils.stacks import get_stack_info, iter_stack_frames, iter_traceback_frames, \
                                       get_culprit

class ModuleProxyCache(dict):
    def __missing__(self, key):
        module, class_name = key.rsplit('.', 1)

        handler = getattr(__import__(module, {}, {}, [class_name], -1), class_name)

        self[key] = handler

        return handler

class Client(object):
    """
    The base Raven client, which handles both local direct communication with Sentry (through
    the GroupedMessage API), as well as communicating over the HTTP API to multiple servers.

    >>> from raven import Client
    >>>
    >>> client = Client(servers=['http://sentry.local/store/'], include_paths=['my.package'])
    >>> try:
    >>>     1/0
    >>> except ZeroDivisionError:
    >>>     ident = client.get_ident(client.create_from_exception())
    >>>     print "Exception caught; reference is %%s" %% ident
    """

    def __init__(self, servers, include_paths=None, exclude_paths=None, timeout=None,
                 name=None, auto_log_stacks=None, key=None, string_max_length=None,
                 list_max_length=None, site=None, public_key=None, secret_key=None,
                 processors=None, **kwargs):
        # servers may be set to a NoneType (for Django)
        if servers and not (key or (secret_key and public_key)):
            raise TypeError('You must specify a key to communicate with the remote Sentry servers.')

        self.servers = servers
        self.include_paths = include_paths or set(defaults.INCLUDE_PATHS)
        self.exclude_paths = exclude_paths or set(defaults.EXCLUDE_PATHS)
        self.timeout = timeout or int(defaults.TIMEOUT)
        self.name = name or unicode(defaults.NAME)
        self.auto_log_stacks = auto_log_stacks or bool(defaults.AUTO_LOG_STACKS)
        self.key = key or defaults.KEY
        self.string_max_length = string_max_length or int(defaults.MAX_LENGTH_STRING)
        self.list_max_length = list_max_length or int(defaults.MAX_LENGTH_LIST)
        self.site = site or unicode(defaults.SITE)
        self.public_key = public_key
        self.secret_key = secret_key

        self.processors = processors or defaults.PROCESSORS
        self.logger = logging.getLogger(__name__)
        self.module_cache = ModuleProxyCache()

    def get_processors(self):
        for processor in self.processors:
            yield self.module_cache[processor](self)

    def get_ident(self, result):
        """
        Returns a searchable string representing a message.

        >>> result = client.process(**kwargs)
        >>> ident = client.get_ident(result)
        """
        return '$'.join(result)

    def capture(self, event_type, data=None, date=None, time_spent=None, event_id=None,
                extra=None, culprit=None, level=None, stack=None, **kwargs):
        """
        Captures and processes an event and pipes it off to SentryClient.send.

        To use structured data (interfaces) with capture:

        >>> capture('Message', message='foo', data={
        >>>     'sentry.interfaces.Http': {
        >>>         'url': '...',
        >>>         'data': {},
        >>>         'querystring': '...',
        >>>         'method': 'POST',
        >>>     },
        >>> }, extra={
        >>>     'key': 'value',
        >>> })

        The finalized ``data`` structure contains the following (some optional) builtin values:

        >>> {
        >>>     # the culprit and version information
        >>>     'culprit': 'full.module.name', # or /arbitrary/path
        >>>     'version': ('full.module.name', 'version string'),
        >>>
        >>>     # all detectable installed modules
        >>>     'modules': {
        >>>         'full.module.name': 'version string',
        >>>     },
        >>>
        >>>     # arbitrary data provided by user
        >>>     'extra': {
        >>>         'key': 'value',
        >>>     }
        >>> }

        :param event_type: the module path to the Event class. Builtins can use shorthand class
                           notation and exclude the full module path.
        :param tags: a list of tuples (key, value) specifying additional tags for event
        :param data: the data base, useful for specifying structured data interfaces. Any key which contains a '.'
                     will be assumed to be a data interface.
        :param date: the datetime of this event
        :param time_spent: a float value representing the duration of the event
        :param event_id: a 32-length unique string identifying this event
        :param extra: a dictionary of additional standard metadata
        :param culprit: a string representing the cause of this event (generally a path to a function)
        :return: a 32-length string identifying this event
        """
        if data is None:
            data = {}
        if extra is None:
            extra = {}
        if date is None:
            date = datetime.datetime.now()
        if stack is None:
            stack = self.auto_log_stacks

        if '.' not in event_type:
            # Assume it's a builtin
            event_type = 'sentry.events.%s' % event_type

        handler = self.module_cache[event_type](self)
        result = handler.capture(**kwargs)

        if not culprit:
            culprit = result.pop('culprit', None)

        for k, v in result.iteritems():
            if k not in data:
                data[k] = v
            else:
                data[k].update(v)

        if stack and 'sentry.interfaces.Stacktrace' not in data:
            frames = varmap(shorten, get_stack_info(iter_stack_frames()))

            data.update({
                'sentry.interfaces.Stacktrace': {
                    'frames': frames
                },
            })

        if 'sentry.interfaces.Stacktrace' in data and not culprit:
            culprit = get_culprit(frames, self.client.include_paths, self.client.exclude_paths)

        if not data['level']:
            data['level'] = level or logging.ERROR
        data['modules'] = versions = get_versions(self.include_paths)
        data['server_name'] = self.name
        data['site'] = self.site
        data.setdefault('extra', {})
        data.setdefault('level', logging.ERROR)

        # Shorten lists/strings
        for k, v in extra.iteritems():
            # a . means its a builtin interfaces
            if '.' not in k:
                continue
            data['extra'][k] = shorten(v, string_length=self.string_max_length, list_length=self.list_max_length)

        if culprit:
            data['culprit'] = culprit

            # get list of modules from right to left
            parts = culprit.split('.')
            module_list = ['.'.join(parts[:idx]) for idx in xrange(1, len(parts)+1)][::-1]
            version = None
            module = None
            for m in module_list:
                if m in versions:
                    module = m
                    version = versions[m]

            # store our "best guess" for application version
            if version:
                data['version'] = (module, version)

        data['checksum'] = checksum = handler.get_hash(data)

        # create ID client-side so that it can be passed to application
        event_id = uuid.uuid4().hex
        data['event_id'] = event_id

        # Run the data through processors
        for processor in self.get_processors():
            data.update(self.module_cache[processor].process(data))

        # Make sure all data is coerced
        data = transform(data)

        if 'timestamp' not in kwargs:
            kwargs['timestamp'] = datetime.datetime.now()

        data['message'] = handler.to_string(data)

        self.send(data=data, date=date, time_spent=time_spent, event_id=event_id)

        return (event_id, checksum)

    def send_remote(self, url, data, headers={}):
        """
        Sends a request to a remote webserver using HTTP POST.
        """
        req = urllib2.Request(url, headers=headers)
        try:
            response = urllib2.urlopen(req, data, self.timeout).read()
        except:
            response = urllib2.urlopen(req, data).read()
        return response

    def send(self, **kwargs):
        """
        Sends the message to the server.

        If ``servers`` was passed into the constructor, this will serialize the data and pipe it to
        each server using ``send_remote()``. Otherwise, this will communicate with ``sentry.models.GroupedMessage``
        directly.
        """
        # if kwargs.get('date'):
        #     kwargs['date'] = kwargs['date'].strftime('%Y-%m-%dT%H:%M:%S.%f')
        message = base64.b64encode(json.dumps(kwargs).encode('zlib'))

        for url in self.servers:
            timestamp = time.time()
            signature = get_signature(message, timestamp, self.secret_key or self.key)
            headers = {
                'X-Sentry-Auth': get_auth_header(signature, timestamp, 'raven/%s' % (raven.VERSION,), self.public_key),
                'Content-Type': 'application/octet-stream',
            }

            try:
                return self.send_remote(url=url, data=message, headers=headers)
            except urllib2.HTTPError, e:
                body = e.read()
                self.logger.error('Unable to reach Sentry log server: %s (url: %%s, body: %%s)' % (e,), url, body,
                             exc_info=True, extra={'data': {'body': body, 'remote_url': url}})
                self.logger.log(kwargs.pop('level', None) or logging.ERROR, kwargs.pop('message', None))
            except urllib2.URLError, e:
                self.logger.error('Unable to reach Sentry log server: %s (url: %%s)' % (e,), url,
                             exc_info=True, extra={'data': {'remote_url': url}})
                self.logger.log(kwargs.pop('level', None) or logging.ERROR, kwargs.pop('message', None))

    def create_from_record(self, record, **kwargs):
        """
        Creates an event for a ``logging`` module ``record`` instance.

        If the record contains an attribute, ``stack``, that evaluates to True,
        it will pass this information on to process in order to grab the stack
        frames.

        >>> class ExampleHandler(logging.Handler):
        >>>     def emit(self, record):
        >>>         self.format(record)
        >>>         client.create_from_record(record)
        """
        data = kwargs.pop('data') or {}

        # If there's no exception being processed, exc_info may be a 3-tuple of None
        # http://docs.python.org/library/sys.html#sys.exc_info
        if record.exc_info and all(record.exc_info):
            handler = self.module_cache['sentry.events.Exception'](self)

            data.update(handler.capture(exc_info=record.exc_info))

        for k in ('url', 'view'):
            data[k] = record.__dict__.get(k)

        if getattr(record, 'data', None):
            extra = record.data
        else:
            extra = kwargs.pop('extra')

        return self.capture('Message', message=record.msg, params=self.args, level=record.levelno,
                            stack=getattr(record, 'stack', None), data=data, extra=extra, **kwargs)

    def create_from_text(self, message, **kwargs):
        """
        Creates an event for from ``message``.

        >>> client.create_from_text('My event just happened!')
        """
        return self.process(
            message=message,
            **kwargs
        )

    def create_from_exception(self, exc_info=None, **kwargs):
        """
        Creates an event from an exception.

        >>> try:
        >>>     exc_info = sys.exc_info()
        >>>     client.create_from_exception(exc_info)
        >>> finally:
        >>>     del exc_info
        """
        return self.capture('Exception', exc_info=exc_info, **kwargs)

class DummyClient(Client):
    "Sends messages into an empty void"
    def send(self, **kwargs):
        return None
