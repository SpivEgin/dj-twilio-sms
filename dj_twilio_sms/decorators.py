# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from functools import wraps
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotAllowed
from django.utils import six
from django.utils.encoding import force_text
from django.views.decorators.csrf import csrf_exempt

from twilio.twiml import TwiML
from twilio.request_validator import RequestValidator

logger = logging.getLogger("dj-twilio-sms.decorators")


def twilio_view(f):
    """This decorator provides several helpful shortcuts for writing Twilio
    views.

        - It ensures that only requests from Twilio are passed through. This
          helps protect you from forged requests.

        - It ensures your view is exempt from CSRF checks via Django's
          @csrf_exempt decorator. This is necessary for any view that accepts
          POST requests from outside the local domain (eg: Twilio's servers).

        - It allows your view to (optionally) return TwiML to pass back to
          Twilio's servers instead of building a ``HttpResponse`` object
          manually.

        - It allows your view to (optionally) return any ``twilio.TwiML`` object
          instead of building a ``HttpResponse`` object manually.

    Usage::

        from twilio.twiml import Response

        @twilio_view
        def my_view(request):
            r = Response()
            r.sms("Thanks for the SMS message!")
            return r
    """
    @csrf_exempt
    @wraps(f)
    def decorator(request, *args, **kwargs):
        # Attempt to gather all required information to allow us to check the
        # incoming HTTP request for forgery. If any of this information is not
        # available, then we'll throw a HTTP 403 error (forbidden).

        # Ensure the request method is POST
        if request.method != "POST":
            logger.error("Twilio: Expected POST request", extra={"request": request})
            return HttpResponseNotAllowed(request.method)

        if not getattr(settings, "TWILIO_SKIP_SIGNATURE_VALIDATION", False):
            # Validate the request
            try:
                validator = RequestValidator(settings.TWILIO_AUTH_TOKEN)
                url = request.build_absolute_uri()
                # Ensure the original requested url is tested for validation
                # Prevents breakage when processed behind a proxy server
                if "HTTP_X_FORWARDED_SERVER" in request.META:
                    url = "{0}://{1}{2}".format(
                        request.META["HTTP_X_FORWARDED_PROTO"], request.META["HTTP_X_FORWARDED_SERVER"], request.META["REQUEST_URI"]
                    )
                signature = request.META["HTTP_X_TWILIO_SIGNATURE"]
            except (AttributeError, KeyError) as e:
                logger.exception("Twilio: Missing META param", extra={"request": request})
                return HttpResponseForbidden("Missing META param: %s" % e)

            # Now that we have all the required information to perform forgery
            # checks, we'll actually do the forgery check.
            if not validator.validate(url, request.POST, signature) and not getattr(settings, "SMS_DEBUG", False):
                logger.error(
                    "Twilio: Invalid url signature %s - %s - %s",
                    url, request.POST, signature, extra={"request": request}
                )
                return HttpResponseForbidden("Invalid signature")

        # Run the wrapped view, and capture the data returned.
        response = f(request, *args, **kwargs)

        # If the view returns a string (or a ``twilio.TwiML`` object), we'll
        # assume it is XML TwilML data and pass it back with the appropriate
        # mimetype. We won't check the XML data because that would be too time
        # consuming for every request. Instead, we'll let the errors pass
        # through to be dealt with by the developer.
        if isinstance(response, six.text_type):
            return HttpResponse(response, mimetype="application/xml")
        elif isinstance(response, TwiML):
            return HttpResponse(force_text(response), mimetype="application/xml")
        else:
            return response
    return decorator
