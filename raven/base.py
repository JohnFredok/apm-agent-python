"""
raven.base
~~~~~~~~~~~~~~~~~~

:copyright: (c) 2010 by the Sentry Team, see AUTHORS for more details.
:license: BSD, see LICENSE for more details.
"""

from __future__ import absolute_import

import base64
import datetime
import hashlib
import logging
import time
import urllib2
import uuid

import raven
from raven.conf import defaults
from raven.utils import json, varmap, get_versions, get_signature, get_auth_header
from raven.utils.encoding import transform, shorten
from raven.utils.stacks import get_stack_info, iter_stack_frames, \
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
                 processors=None, project=1, **kwargs):
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
        self.project = project

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

    def get_handler(self, name):
        return self.module_cache[name](self)

    def capture(self, event_type, data=None, date=None, time_spent=None, event_id=None,
                extra=None, stack=None, **kwargs):
        """
        Captures and processes an event and pipes it off to SentryClient.send.

        To use structured data (interfaces) with capture:

        >>> capture('Message', message='foo', data={
        >>>     'sentry.interfaces.Http': {
        >>>         'url': '...',
        >>>         'data': {},
        >>>         'query_string': '...',
        >>>         'method': 'POST',
        >>>     },
        >>> }, extra={
        >>>     'key': 'value',
        >>> })

        The finalized ``data`` structure contains the following (some optional) builtin values:

        >>> {
        >>>     # the culprit and version information
        >>>     'culprit': 'full.module.name', # or /arbitrary/path
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
            event_type = 'raven.events.%s' % event_type

        handler = self.get_handler(event_type)
        result = handler.capture(**kwargs)

        # data (explicit) culprit takes over auto event detection
        culprit = result.pop('culprit', None)
        if data.get('culprit'):
            culprit = data['culprit']

        for k, v in result.iteritems():
            if k not in data:
                data[k] = v
            else:
                data[k].update(v)

        if stack and 'sentry.interfaces.Stacktrace' not in data:
            if stack is True:
                frames = iter_stack_frames()

            else:
                frames = stack

            data.update({
                'sentry.interfaces.Stacktrace': {
                    'frames': varmap(shorten, get_stack_info(frames))
                },
            })

        if 'sentry.interfaces.Stacktrace' in data and not culprit:
            culprit = get_culprit(data['sentry.interfaces.Stacktrace']['frames'], self.include_paths, self.exclude_paths)

        if not data.get('level'):
            data['level'] = logging.ERROR
        data['modules'] = get_versions(self.include_paths)
        data['server_name'] = self.name
        data['site'] = self.site
        data.setdefault('extra', {})
        data.setdefault('level', logging.ERROR)

        # Shorten lists/strings
        for k, v in extra.iteritems():
            data['extra'][k] = shorten(v, string_length=self.string_max_length, list_length=self.list_max_length)

        if culprit:
            data['culprit'] = culprit

        checksum = hashlib.md5()
        for bit in handler.get_hash(data):
            checksum.update(bit or '')
        data['checksum'] = checksum = checksum.hexdigest()

        # create ID client-side so that it can be passed to application
        event_id = uuid.uuid4().hex
        data['event_id'] = event_id

        # Run the data through processors
        for processor in self.get_processors():
            data.update(processor.process(data))

        # Make sure all data is coerced
        data = transform(data)

        if 'timestamp' not in kwargs:
            kwargs['timestamp'] = datetime.datetime.utcnow()

        data['message'] = handler.to_string(data)

        data.update({
            'date': date,
            'time_spent': time_spent,
            'event_id': event_id,
            'project': self.project,
        })

        self.send(**data)

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

    def send(self, **data):
        """
        Sends the message to the server.

        If ``servers`` was passed into the constructor, this will serialize the data and pipe it to
        each server using ``send_remote()``. Otherwise, this will communicate with ``sentry.models.GroupedMessage``
        directly.
        """
        # if kwargs.get('date'):
        #     kwargs['date'] = kwargs['date'].strftime('%Y-%m-%dT%H:%M:%S.%f')
        message = base64.b64encode(json.dumps(data).encode('zlib'))

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
                self.logger.log(data.pop('level', None) or logging.ERROR, data.pop('message', None))
            except urllib2.URLError, e:
                self.logger.error('Unable to reach Sentry log server: %s (url: %%s)' % (e,), url,
                             exc_info=True, extra={'data': {'remote_url': url}})
                self.logger.log(data.pop('level', None) or logging.ERROR, data.pop('message', None))

    def create_from_text(self, message, **kwargs):
        """
        Creates an event for from ``message``.

        >>> client.create_from_text('My event just happened!')
        """
        return self.capture('Message', message=message, **kwargs)

    def create_from_exception(self, exc_info=None, **kwargs):
        """
        Creates an event from an exception.

        >>> try:
        >>>     exc_info = sys.exc_info()
        >>>     client.create_from_exception(exc_info)
        >>> finally:
        >>>     del exc_info

        If exc_info is not provided, or is set to True, then this method will
        perform the ``exc_info = sys.exc_info()`` and the requisite clean-up
        for you.
        """
        return self.capture('Exception', exc_info=exc_info, **kwargs)

class DummyClient(Client):
    "Sends messages into an empty void"
    def send(self, **kwargs):
        return None
