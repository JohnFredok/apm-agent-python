import logging
import sys

from django.http import HttpRequest
from django.template import TemplateSyntaxError
from django.template.loader import LoaderOrigin

from sentry_client.base import SentryClient

logger = logging.getLogger('sentry.errors.client')

class DjangoClient(SentryClient):
    def process(self, **kwargs):
        request = kwargs.pop('request', None)
        is_http_request = isinstance(request, HttpRequest)
        if is_http_request:
            if not request.POST and request.raw_post_data:
                post_data = request.raw_post_data
            else:
                post_data = request.POST

            kwargs['data'].update(dict(
                META=request.META,
                POST=post_data,
                GET=request.GET,
                COOKIES=request.COOKIES,
            ))

            if hasattr(request, 'user'):
                if request.user.is_authenticated():
                    user_info = {
                        'is_authenticated': True,
                        'id': request.user.pk,
                        'username': request.user.username,
                        'email': request.user.email,
                    }
                else:
                    user_info = {
                        'is_authenticated': False,
                    }

                kwargs['data']['__sentry__']['user'] = user_info

            if not kwargs.get('url'):
                kwargs['url'] = request.build_absolute_uri()
        else:
            kwargs['request'] = request

        message_id, checksum = super(DjangoClient, self).process(**kwargs)

        if is_http_request:
            # attach the sentry object to the request
            request.sentry = {
                'id': '%s$%s' % (message_id, checksum),
                'thrashed': False,
            }

        return message_id, checksum

    def create_from_exception(self, exc_info=None, **kwargs):
        """
        Creates an error log from an exception.
        """
        new_exc = bool(exc_info)
        if not exc_info or exc_info is True:
            exc_info = sys.exc_info()

        data = kwargs.pop('data', {}) or {}

        try:
            exc_type, exc_value, exc_traceback = exc_info

            # As of r16833 (Django) all exceptions may contain a ``django_template_source`` attribute (rather than the
            # legacy ``TemplateSyntaxError.source`` check) which describes template information.
            if hasattr(exc_value, 'django_template_source') or ((isinstance(exc_value, TemplateSyntaxError) and \
                isinstance(getattr(exc_value, 'source', None), (tuple, list)) and isinstance(exc_value.source[0], LoaderOrigin))):
                origin, (start, end) = getattr(exc_value, 'django_template_source', exc_value.source)
                data['__sentry__']['template'] = (origin.reload(), start, end, origin.name)
                kwargs['view'] = origin.loadname

            return super(DjangoClient, self).create_from_exception(exc_info, **kwargs)
        finally:
            if new_exc:
                try:
                    del exc_info
                except Exception, e:
                    logger.exception(e)
