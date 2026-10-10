"""TLS startup probe uses the existing unauthorized-response boundary."""
import os
import ssl
from urllib.error import HTTPError
from urllib.request import Request, urlopen

context = ssl.create_default_context(cafile=os.environ['OMNEUM_NETWORK_TLS_CERT'])
# Probe only this container's loopback listener, pinned to its mounted cert.
# A production certificate names the public endpoint rather than localhost.
context.check_hostname = False
context.verify_flags |= ssl.VERIFY_X509_PARTIAL_CHAIN
try:
    urlopen(Request('https://localhost:8443/v1/voprf', data=b'{}', method='POST'),
            context=context, timeout=3)
except HTTPError as error:
    if error.code != 401:
        raise SystemExit(1)
else:
    raise SystemExit(1)
