from aiohttp.web import Request, json_response
from aiohttp.web import Response as WebResponse


class Response:
    def __init__(self, status: int = 200, **kwargs):
        self.attrs = kwargs
        self.status = status

    def to_response(self):
        return json_response(self.attrs, status=self.status)

    def __setitem__(self, key, value):
        self.attrs[key] = value

    def __getitem__(self, item):
        return self.attrs[item]


class TextResponse(Response):
    def __init__(self, message: str, status: int = 200):
        super(TextResponse, self).__init__(
            status=status,
            message=message
        )

    def to_response(self):
        return WebResponse(text=self.attrs["message"], status=self.status)


class HTTPError(Response, Exception):
    def __init__(self, *, status: int, message: str, **kwargs):
        super(HTTPError, self).__init__(
            message=message,
            status=status,
            **kwargs
        )


def convert_response(ignore):
    async def _outer(app, handler):
        async def _inner(request: Request):
            try:
                rtn = await handler(request)
            except HTTPError as err:
                rtn = err
            if request.method == "OPTIONS":
                return rtn
            if request.path in ignore:
                return rtn
            assert isinstance(rtn, Response), "Not using local response class."
            return rtn.to_response()
        return _inner
    return _outer
