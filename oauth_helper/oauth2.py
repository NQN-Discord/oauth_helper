from typing import Optional, Dict
from discord.http import HTTPClient, Route
from discord.errors import HTTPException
from discord import User, Client
import aiohttp
import time
from cachetools import TTLCache

from .response import HTTPError
from .exceptions import TypeCheckError


def oauth2_handler(config: Dict[str, str], bot: Client, allow_dbl: bool = False):
    wrapper = oauth2_wrapper(config, bot)

    async def _middleware(app, handler):
        async def _inner(request):
            auth = request.headers.get("Authorization", None)
            if auth in [None, ""] or (allow_dbl and request.headers.get("User-Agent") in {"DBL", ""}):
                request["oauth"] = oauth = None
            else:
                try:
                    request["oauth"] = oauth = await wrapper.from_refresh_token(auth, config["refresh_uri"])
                except InvalidTokenError:
                    return HTTPError(message="Invalid login token", status=403)
            request["from_code"] = wrapper.from_code
            try:
                rtn = await handler(request)
            except InvalidTokenError:
                return HTTPError(message="Invalid login token", status=403)
            except TypeCheckError as err:
                rtn = HTTPError(
                    message=str(err),
                    status=400
                )
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
    def __init__(self):
        self._cache = {}

    def get_token(self, refresh_token):
        if refresh_token not in self._cache:
            raise NotInCacheError()
        access_token, expires, scope = self._cache[refresh_token]
        if expires <= time.time():
            del self._cache[refresh_token]
            raise NotInCacheError()
        return {"access_token": access_token, "scope": scope}

    def add_access_token(self, refresh_token, access_token, expires, scope):
        self._cache[refresh_token] = (access_token, time.time() + expires, scope)


def oauth2_wrapper(config, bot):
    cache = TokenCache()
    user_id_cache = TTLCache(ttl=36000, maxsize=500)

    class Oauth2:
        def __init__(self, access_token, refresh_token, redirect_uri, scope, guild_id=None):
            self.access_token = access_token
            self.refresh_token = refresh_token
            self.redirect_uri = redirect_uri
            self.scopes = scope.split(" ")
            self.guild_id = guild_id

        def __repr__(self):
            return f"Oauth2(access_token={self.access_token!r}, refresh_token={self.refresh_token!r}, redirect_uri={self.redirect_uri!r}, scope={' '.join(self.scopes)!r})"

        async def __aenter__(self):
            self._http = HTTPClient()
            self._http._HTTPClient__session = aiohttp.ClientSession(connector=self._http.connector)
            self._http.token = f"Bearer {self.access_token}"
            orig_request = self._http.request

            async def request(route, *args, **kwargs):
                try:
                    return await orig_request(route, **kwargs)
                except HTTPException as e:
                    if e.response.status == 401:
                        json_data = await self._create_from_refresh_token(self.refresh_token, self.redirect_uri)
                        if "access_token" not in json_data:
                            raise InvalidTokenError()
                        self.access_token = json_data["access_token"]
                        self._http.token = f"Bearer {self.access_token}"
                        return await orig_request(route, *args, **kwargs)
                    raise

            self._http.request = request

            return self._http

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            await self._http.close()
            return False

        async def get_user_info(self):
            try:
                return user_id_cache[self.refresh_token]
            except KeyError:
                async with self as http:
                    rtn = user_id_cache[self.refresh_token] = User(
                        data=await http.get_user("@me"),
                        state=NotImplemented
                    )
                    return rtn

        async def get_guilds(self):
            if "guilds" in self.scopes:
                async with self as http:
                    return await http.get_guilds(100)
            else:
                return []

        async def join_guild(self, guild_id: int, user_id: int, access_token: str, **kwargs) -> Optional[str]:
            r = Route('PUT', '/guilds/{guild_id}/members/{user_id}', guild_id=guild_id, user_id=user_id)
            try:
                await bot.http.request(r, json={
                    "access_token": access_token,
                    **kwargs
                })
                return None
            except HTTPException as e:
                return e.text

        @classmethod
        async def from_code(cls, code, redirect_uri):
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
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                ) as res:
                    return cls.create_from_json(await res.json(), redirect_uri)

        @classmethod
        async def from_refresh_token(cls, refresh_token, redirect_uri):
            try:
                return Oauth2(
                    refresh_token=refresh_token,
                    redirect_uri=redirect_uri,
                    **cache.get_token(refresh_token))
            except NotInCacheError:
                pass
            return cls.create_from_json(
                await cls._create_from_refresh_token(refresh_token, redirect_uri),
                redirect_uri
            )

        @staticmethod
        async def _create_from_refresh_token(refresh_token, redirect_uri):
            config_data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "redirect_uri": redirect_uri
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        "https://discord.com/api/v6/oauth2/token",
                        data=config_data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                ) as res:
                    return await res.json()

        @classmethod
        def create_from_json(cls, json, redirect_uri):
            if "refresh_token" not in json:
                raise InvalidTokenError()
            cache.add_access_token(
                json["refresh_token"],
                json["access_token"],
                json["expires_in"],
                json["scope"]
            )
            return Oauth2(
                json["access_token"],
                json["refresh_token"],
                redirect_uri,
                json["scope"],
                "guild" in json and int(json["guild"]["id"]) or None
            )

    return Oauth2
