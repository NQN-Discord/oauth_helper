from __future__ import annotations

from types import TracebackType
from typing import (
    Optional,
    Dict,
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Tuple,
    MutableMapping,
    List,
    Protocol,
    Type,
    TYPE_CHECKING,
    cast,
)

from aiohttp import ClientResponse
from aiohttp.web_app import Application
from aiohttp.web_request import Request
from discord.http import HTTPClient, Route
from discord.errors import HTTPException
from discord import User, Client
import aiohttp
import time
from cachetools import TTLCache
import asyncio

from .response import HTTPError, Response
from .exceptions import TypeCheckError


if TYPE_CHECKING:
    from discord.types import guild


def oauth2_handler(
    config: Dict[str, str],
    bot: Client,
    allow_dbl: bool = False,
) -> Callable[
    [Application, Callable[[Request], Awaitable[Response]]],
    Coroutine[Any, Any, Callable[[Request], Awaitable[Response]]],
]:
    wrapper = oauth2_wrapper(config, bot)

    async def _middleware(
        app: Application,
        handler: Callable[[Request], Awaitable[Response]],
    ) -> Callable[[Request], Awaitable[Response]]:
        async def _inner(request: Request) -> Response:
            auth = request.headers.get("Authorization", None)
            if auth in [None, ""] or (
                allow_dbl and "Top.gg" in request.headers.get("User-Agent", "")
            ):
                request["oauth"] = oauth = None
            else:
                assert auth is not None
                try:
                    request["oauth"] = oauth = await wrapper.from_refresh_token(
                        auth, config["refresh_uri"]
                    )
                except InvalidTokenError:
                    return HTTPError(message="Invalid login token", status=403)
            request["from_code"] = wrapper.from_code
            try:
                rtn = await handler(request)
            except InvalidTokenError:
                return HTTPError(message="Invalid login token", status=403)
            except TypeCheckError as err:
                rtn = HTTPError(message=str(err), status=400)
            if oauth and oauth.refresh_token != auth:
                rtn["authorization"] = oauth.refresh_token
            return rtn

        return _inner

    return _middleware


class NotInCacheError(Exception):
    pass


class InvalidTokenError(Exception):
    pass


class TokenCache:
    def __init__(self) -> None:
        self._cache: Dict[str, Tuple[str, float, str]] = {}

    def get_token(self, refresh_token: str) -> Dict[str, str]:
        if refresh_token not in self._cache:
            raise NotInCacheError()
        access_token, expires, scope = self._cache[refresh_token]
        if expires <= time.time():
            del self._cache[refresh_token]
            raise NotInCacheError()
        return {"access_token": access_token, "scope": scope}

    def add_access_token(
        self,
        refresh_token: str,
        access_token: str,
        expires: int,
        scope: str,
    ) -> None:
        self._cache[refresh_token] = (access_token, time.time() + expires, scope)


class Oauth2Protocol(Protocol):
    access_token: str
    refresh_token: Optional[str]
    redirect_uri: str
    scopes: List[str]
    guild_id: Optional[int]

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str],
        redirect_uri: str,
        scope: str,
        guild_id: Optional[int],
    ): ...

    def __repr__(self) -> str: ...

    async def __aenter__(self) -> HTTPClient: ...

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> bool: ...

    async def get_user_info(self) -> User: ...

    async def get_guilds(self) -> List[guild.Guild]: ...

    async def join_guild(
        self, guild_id: int, user_id: int, access_token: str, **kwargs: Any
    ) -> Optional[str]: ...

    @classmethod
    async def from_code(cls, code: str, redirect_uri: str) -> "Oauth2Protocol": ...

    @classmethod
    async def from_refresh_token(
        cls, refresh_token: str, redirect_uri: str
    ) -> "Oauth2Protocol": ...

    @classmethod
    def from_access_token(
        cls, access_token: str, redirect_uri: str
    ) -> "Oauth2Protocol": ...

    @classmethod
    def create_from_json(
        cls, json: Dict[str, Any], redirect_uri: str
    ) -> "Oauth2Protocol": ...


def oauth2_wrapper(config: Dict[str, str], bot: Client) -> Type[Oauth2Protocol]:
    cache = TokenCache()
    user_id_cache: MutableMapping[str, User] = TTLCache(ttl=36000, maxsize=500)

    class Oauth2:
        def __init__(
            self,
            access_token: str,
            refresh_token: Optional[str],
            redirect_uri: str,
            scope: str,
            guild_id: Optional[int],
        ):
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.redirect_uri = redirect_uri
            self.scopes = scope.split(" ")
            self.guild_id = guild_id

        def __repr__(self) -> str:
            return f"Oauth2(access_token={self.access_token!r}, refresh_token={self.refresh_token!r}, redirect_uri={self.redirect_uri!r}, scope={' '.join(self.scopes)!r})"

        async def __aenter__(self) -> HTTPClient:
            loop = asyncio.get_event_loop()
            connector = aiohttp.TCPConnector(loop=loop, limit=0)
            self._http = HTTPClient(connector=connector, loop=loop)
            self._http._HTTPClient__session = self._http._HTTPClient__session = (  # type: ignore
                aiohttp.ClientSession(connector=connector)
            )
            self._http.token = NoConcatString(f"Bearer {self.access_token}")
            self._http._global_over = asyncio.Event()
            self._http._global_over.set()

            orig_request = self._http.request

            async def request(route: Route, *args: Any, **kwargs: Any) -> Any:
                try:
                    return await orig_request(route, **kwargs)
                except HTTPException as e:
                    if cast(ClientResponse, e.response).status == 401:
                        if self.refresh_token is None:
                            raise InvalidTokenError()
                        json_data = await self._create_from_refresh_token(
                            self.refresh_token, self.redirect_uri
                        )
                        if "access_token" not in json_data:
                            raise InvalidTokenError()
                        self.access_token = json_data["access_token"]
                        self._http.token = f"Bearer {self.access_token}"
                        return await orig_request(route, *args, **kwargs)
                    raise

            self._http.request = request  # type: ignore

            return self._http

        async def __aexit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc_val: Optional[BaseException],
            exc_tb: Optional[TracebackType],
        ) -> bool:
            await self._http.close()
            return False

        async def get_user_info(self) -> User:
            try:
                return user_id_cache[self.access_token]
            except KeyError:
                async with self as http:
                    rtn = user_id_cache[self.access_token] = User(
                        data=await http.get_user("@me"), state=NotImplemented
                    )
            return rtn

        async def get_guilds(self) -> List[guild.Guild]:
            if "guilds" in self.scopes:
                async with self as http:
                    return await http.get_guilds(200)
            return []

        async def join_guild(
            self, guild_id: int, user_id: int, access_token: str, **kwargs: Any
        ) -> Optional[str]:
            r = Route(
                "PUT",
                "/guilds/{guild_id}/members/{user_id}",
                guild_id=guild_id,
                user_id=user_id,
            )
            try:
                await bot.http.request(r, json={"access_token": access_token, **kwargs})
                return None
            except HTTPException as e:
                return e.text

        @classmethod
        async def from_code(cls, code: str, redirect_uri: str) -> "Oauth2Protocol":
            config_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://discord.com/api/v6/oauth2/token",
                    data=config_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as res:
                    return cls.create_from_json(await res.json(), redirect_uri)

        @classmethod
        async def from_refresh_token(
            cls, refresh_token: str, redirect_uri: str
        ) -> "Oauth2Protocol":
            try:
                return Oauth2(
                    refresh_token=refresh_token,
                    redirect_uri=redirect_uri,
                    **cache.get_token(refresh_token),  # type: ignore
                )
            except NotInCacheError:
                pass
            return cls.create_from_json(
                await cls._create_from_refresh_token(refresh_token, redirect_uri),
                redirect_uri,
            )

        @staticmethod
        async def _create_from_refresh_token(
            refresh_token: str, redirect_uri: str
        ) -> Dict[str, Any]:
            config_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": redirect_uri,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://discord.com/api/v6/oauth2/token",
                    data=config_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as res:
                    return await res.json()  # type: ignore

        @classmethod
        def from_access_token(
            cls, access_token: str, redirect_uri: str
        ) -> "Oauth2Protocol":
            return Oauth2(
                access_token,
                refresh_token=None,
                redirect_uri=redirect_uri,
                scope="",
                guild_id=None,
            )

        @classmethod
        def create_from_json(
            cls, json: Dict[str, Any], redirect_uri: str
        ) -> "Oauth2Protocol":
            if "refresh_token" not in json:
                raise InvalidTokenError()
            cache.add_access_token(
                json["refresh_token"],
                json["access_token"],
                json["expires_in"],
                json["scope"],
            )
            return Oauth2(
                json["access_token"],
                json["refresh_token"],
                redirect_uri,
                json["scope"],
                "guild" in json and int(json["guild"]["id"]) or None,
            )

    return Oauth2


class NoConcatString(str):
    def __radd__(self, other: Any) -> str:
        return self
