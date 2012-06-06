import logging
from unittest2 import TestCase
from opbeat_python.base import Client
from opbeat_python.handlers.logging import SentryHandler
from opbeat_python.utils.stacks import iter_stack_frames


class TempStoreClient(Client):
    def __init__(self, servers=None, **kwargs):
        self.events = []
        super(TempStoreClient, self).__init__(servers=servers, **kwargs)

    def send(self, **kwargs):
        self.events.append(kwargs)


class LoggingIntegrationTest(TestCase):
    def setUp(self):
        self.client = TempStoreClient(include_paths=['tests', 'opbeat_python'])
        self.handler = SentryHandler(self.client)
        self.logger = logging.getLogger(__name__)
        self.logger.handlers = []
        self.logger.addHandler(self.handler)

    def test_logger_basic(self):
        self.logger.error('This is a test error')

        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertEquals(event['logger'], __name__)
        self.assertEquals(event['level'], logging.ERROR)
        # self.assertEquals(event['message'], 'This is a test error')
        self.assertFalse('stacktrace' in event)
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        self.assertEquals(msg['message'], 'This is a test error')
        self.assertEquals(msg['params'], ())

    def test_logger_warning(self):
        self.logger.warning('This is a test warning')
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertEquals(event['logger'], __name__)
        self.assertEquals(event['level'], logging.WARNING)
        # self.assertEquals(event['message'], 'This is a test warning')
        self.assertFalse('stacktrace' in event)
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        self.assertEquals(msg['message'], 'This is a test warning')
        self.assertEquals(msg['params'], ())

    def test_logger_extra_data(self):
        self.logger.info('This is a test info with a url', extra=dict(
            data=dict(
                url='http://example.com',
            ),
        ))
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertEquals(event['extra']['url'], 'http://example.com')
        self.assertFalse('stacktrace' in event)
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        self.assertEquals(msg['message'], 'This is a test info with a url')
        self.assertEquals(msg['params'], ())

    def test_logger_exc_info(self):
        try:
            raise ValueError('This is a test ValueError')
        except ValueError:
            self.logger.info('This is a test info with an exception', exc_info=True)

        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)

        # self.assertEquals(event['message'], 'This is a test info with an exception')
        self.assertTrue('stacktrace' in event)
        self.assertTrue('exception' in event)
        exc = event['exception']
        self.assertEquals(exc['type'], 'ValueError')
        self.assertEquals(exc['value'], 'This is a test ValueError')
        self.assertTrue('message' in event)
        msg = event['message']
        self.assertEquals(msg['message'], 'This is a test info with an exception')
        self.assertEquals(msg['params'], ())

    def test_message_params(self):
        self.logger.info('This is a test of %s', 'args')
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        # self.assertEquals(event['message'], 'This is a test of args')
        # print event.keys()
        self.assertFalse('stacktrace' in event)
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        self.assertEquals(msg['message'], 'This is a test of %s')
        self.assertEquals(msg['params'], ('args',))

    def test_record_stack(self):
        self.logger.info('This is a test of stacks', extra={'stack': True})
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertTrue('stacktrace' in event)
        frames = event['stacktrace']['frames']
        self.assertNotEquals(len(frames), 1)
        frame = frames[0]
        self.assertEquals(frame['module'], __name__)
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        # self.assertEquals(msg['message'], 'This is a test of stacks')
        self.assertEquals(msg['params'], ())
        self.assertEquals(event['culprit'], 'tests.handlers.logging.tests.test_record_stack')
        # self.assertEquals(event['message'], 'This is a test of stacks')

    def test_no_record_stack(self):
        self.logger.info('This is a test of no stacks', extra={'stack': False})
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertEquals(event.get('culprit'), None)
        # self.assertEquals(event['message'], 'This is a test of no stacks')
        self.assertFalse('stacktrace' in event)
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        # self.assertEquals(msg['message'], 'This is a test of no stacks')
        self.assertEquals(msg['params'], ())

    def test_explicit_stack(self):
        self.logger.info('This is a test of stacks', extra={'stack': iter_stack_frames()})
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertTrue('culprit' in event, event)
        self.assertEquals(event['culprit'], 'tests.handlers.logging.tests.test_explicit_stack')
        self.assertTrue('message' in event, event)
        # self.assertEquals(event['message'], 'This is a test of stacks')
        self.assertFalse('exception' in event)
        self.assertTrue('message' in event)
        msg = event['message']
        # self.assertEquals(msg['message'], 'This is a test of stacks')
        self.assertEquals(msg['params'], ())
        self.assertTrue('stacktrace' in event)

    def test_extra_culprit(self):
        self.logger.info('This is a test of stacks', extra={'culprit': 'foo.bar'})
        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)
        self.assertEquals(event['culprit'], 'foo.bar')

    def test_logger_exception(self):
        try:
            raise ValueError('This is a test ValueError')
        except ValueError:
            self.logger.exception('This is a test with an exception')

        self.assertEquals(len(self.client.events), 1)
        event = self.client.events.pop(0)

        self.assertEquals(event['message'], 'This is a test with an exception')
        self.assertTrue('stacktrace' in event)
        self.assertTrue('exception' in event)
        exc = event['exception']
        self.assertEquals(exc['type'], 'ValueError')
        self.assertEquals(exc['value'], 'This is a test ValueError')
        self.assertTrue('message' in event)
        msg = event['message']
        # self.assertEquals(msg['message'], 'This is a test with an exception')
        self.assertEquals(msg['params'], ())


class LoggingHandlerTest(TestCase):
    def test_client_arg(self):
        client = TempStoreClient(include_paths=['tests'])
        handler = SentryHandler(client)
        self.assertEquals(handler.client, client)

    def test_client_kwarg(self):
        client = TempStoreClient(include_paths=['tests'])
        handler = SentryHandler(client=client)
        self.assertEquals(handler.client, client)

    # def test_args_as_servers_and_keys(self):
    #     handler = SentryHandler(['http://sentry.local/api/store/'], project_id="project_id", api_key="key")
    #     self.assertTrue(isinstance(handler.client, Client))

    # def test_args_as_servers_and_key(self):
    #     handler = SentryHandler(['http://sentry.local/api/store/'], 'KEY')
    #     self.assertTrue(isinstance(handler.client, Client))

    # def test_first_arg_as_dsn(self):
    #     handler = SentryHandler('http://public:secret@example.com/1')
    #     self.assertTrue(isinstance(handler.client, Client))

    # def test_custom_client_class(self):
    #     handler = SentryHandler('http://public:secret@example.com/1', client_cls=TempStoreClient)
    #     self.assertTrue(type(handler.client), TempStoreClient)

    def test_invalid_first_arg_type(self):
        self.assertRaises(ValueError, SentryHandler, object)
