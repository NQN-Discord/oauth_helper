from __future__ import annotations

import discord
from aiohttp.web import Request
from aiohttp.web_app import Application
from discord import Guild, Member
from typing import Optional, Any, Callable, Awaitable, List, TYPE_CHECKING

from .oauth2 import Oauth2Protocol
from .response import HTTPError, Response

if TYPE_CHECKING:
    from discord.types import guild


not_logged_in_error = HTTPError(
    message="You need to be logged in to use this endpoint",
    status=403,
)


def require_logged_in(func: Any) -> Any:
    func.require_logged_in = True
    return func


async def attach_user(
    app: Application,
    handler: Callable[[Request], Awaitable[Response]],
) -> Callable[[Request], Awaitable[Response]]:
    async def _inner(request: Request) -> Response:
        if request["oauth"] is None:
            if getattr(handler, "require_logged_in", False):
                return not_logged_in_error
            request["user"] = None
        else:
            request["user"] = User(request["oauth"])
        return await handler(request)

    return _inner


class User:
    def __init__(self, oauth: Oauth2Protocol):
        self._oauth = oauth
        self._id = -1

    def __str__(self) -> str:
        return f"User({self._oauth})"

    async def user_info(self) -> discord.User:
        user = await self._oauth.get_user_info()
        self._id = user.id
        return user

    async def guilds(self) -> List[guild.Guild]:
        guilds = await self._oauth.get_guilds()
        return guilds

    async def fetch_member(self, guild: Guild) -> Optional[Member]:
        if self._id == -1:
            return None
        member = guild.get_member(self._id)
        if member is None:
            member = await guild.fetch_member(self._id)
        return member
