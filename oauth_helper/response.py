from typing import Any, Optional, Awaitable, Callable, List, Coroutine

from aiohttp import web_response
from aiohttp.web import Application
from aiohttp.web import Request, json_response
from aiohttp.web import Response as WebResponse


class Response:
    def __init__(self, status: int = 200, **kwargs: Any):
        self.attrs = kwargs
        self.status = status

    def to_response(self) -> web_response.Response:
        return json_response(self.attrs, status=self.status)

    def __setitem__(self, key: str, value: Any) -> None:
        self.attrs[key] = value

    def __getitem__(self, item: str) -> Any:
        return self.attrs[item]


class TextResponse(Response):
    def __init__(
        self, message: str, status: int = 200, *, content_type: Optional[str] = None
    ):
        super(TextResponse, self).__init__(status=status, message=message)
        self.content_type = content_type

    def to_response(self) -> web_response.Response:
        return WebResponse(
            text=self.attrs["message"],
            status=self.status,
            content_type=self.content_type,
        )


class HTTPError(Response, Exception):
    def __init__(self, *, status: int, message: str, **kwargs: Any):
        super(HTTPError, self).__init__(message=message, status=status, **kwargs)


def convert_response(
    ignore: List[str],
) -> Callable[
    [Application, Callable[[Request], Awaitable[Response]]],
    Coroutine[Any, Any, Callable[[Request], Awaitable[web_response.Response]]],
]:
    async def _outer(
        app: Application,
        handler: Callable[[Request], Awaitable[Response | web_response.Response]],
    ) -> Callable[[Request], Awaitable[web_response.Response]]:
        async def _inner(request: Request) -> web_response.Response:
            try:
                rtn = await handler(request)
            except HTTPError as err:
                rtn = err
            if request.method == "OPTIONS":
                return rtn  # type: ignore
            if request.path in ignore:
                return rtn  # type: ignore
            assert isinstance(rtn, Response), "Not using local response class."
            return rtn.to_response()

        return _inner

    return _outer
