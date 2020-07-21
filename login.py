from aiohttp.web import Request
from discord import Guild, Member
from typing import Optional
from .response import HTTPError


def require_logged_in(func):
    func.require_logged_in = True
    return func


async def attach_user(app, handler):
    async def _inner(request: Request):
        if request["oauth"] is None:
            if getattr(handler, "require_logged_in", False):
                return HTTPError(
                    message="You need to be logged in to use this endpoint",
                    status=403
                )
            request["user"] = None
        else:
            request["user"] = User(request["oauth"])
        return await handler(request)
    return _inner


class User:
    def __init__(self, oauth):
        self._oauth = oauth
        self._id = -1

    def __str__(self):
        return f"User({self._oauth})"

    async def user_info(self):
        user = await self._oauth.get_user_info()
        self._id = user.id
        return user

    async def guilds(self):
        guilds = await self._oauth.get_guilds()
        return guilds

    async def fetch_member(self, guild: Guild) -> Optional[Member]:
        if self._id == -1:
            return
        member = guild.get_member(self._id)
        if member is None:
            member = await guild.fetch_member(self._id)
        return member
