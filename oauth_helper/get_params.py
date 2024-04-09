from typing import Any, Type, Dict, Optional, Collection, NamedTuple, Tuple, Union

from typing import _GenericAlias  # type: ignore

import json
from collections import namedtuple

from aiohttp.web_request import Request

from oauth_helper import HTTPError
from .exceptions import TypeCheckError, CastError, ArgsError


async def get_params(
    request: Request,
    annotations: Dict[str, Type[Any]],
    cast: bool = True,
) -> NamedTuple:
    if request.method in {"POST", "PUT", "DELETE"}:
        try:
            query = await request.json()
        except json.decoder.JSONDecodeError:
            raise HTTPError(status=400, message="Invalid JSON")
    else:
        query = {}
        for key in request.rel_url.query.keys():
            if key.endswith("[]"):
                query[key.rstrip("[]")] = request.rel_url.query.getall(key)
            else:
                query[key] = request.rel_url.query.get(key)
    try:
        typecheck_class(query, annotations, cast=cast)
    except CastError as e:
        raise HTTPError(
            status=400,
            message=f"{e.value} was not of type `{e.type.__name__}`",
        )
    except ArgsError as e:
        raise HTTPError(
            status=400,
            message="Invalid parameters passed",
            model=e.model,
            expected=e.expected,
            got=e.got,
        )
    rtn_type = namedtuple("RequestQuery", query.keys())  # type: ignore
    return rtn_type(**query)


def is_namedtuple(x: Any) -> bool:
    try:
        return tuple in x.__bases__ and hasattr(x, "_fields")
    except AttributeError:
        return False


def typecheck_single(x: Any, t: Type[Any], cast: bool = False) -> Optional[Any]:
    if t is Any:
        return None
    if isinstance(t, _GenericAlias):
        if repr(t).startswith(("typing.Union", "typing.Optional")):
            for t2 in t.__args__:
                try:
                    return typecheck_single(x, t2, cast)
                except TypeCheckError:
                    pass
            raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
        if t._name == "Dict":
            typecheck_dict(x, t)
            return None
        if x == "":
            return []
        if t._name == "List":
            typecheck_collection(x, t, list)
            return None
        if t._name == "Set":
            typecheck_collection(
                x, t, (set, list)
            )  # Special case these for deserialising being crap
            return None
    elif is_namedtuple(t):
        typecheck_class(x, t.__annotations__)
        return None
    try:
        isinstance(x, t)
    except TypeError:
        pass
    else:
        if not isinstance(x, t):
            if cast:
                try:
                    return t(x)
                except:
                    raise CastError(t, x)
            raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
        return None
    raise NotImplementedError(f"Unable to find type of variable: {type(x)}: {t}")


def typecheck_collection(
    x: Collection[Any],
    t: Type[Any],
    correct: Union[Type[Any], Tuple[Type[Any], ...]],
) -> None:
    (of,) = t.__args__
    if not isinstance(x, correct):
        raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
    for i in x:
        typecheck_single(i, of)


def typecheck_dict(x: Dict[Any, Any], t: Type[Any]) -> None:
    keys, values = t.__args__
    if not isinstance(x, dict):
        raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
    for k, v in x.items():
        typecheck_single(k, keys)
        typecheck_single(v, values)


def typecheck_class(x: Any, t: Dict[str, Type[Any]], cast: bool = False) -> None:
    if not isinstance(x, dict):
        _dict = x.__dict__
    else:
        _dict = x
    if len(_dict) != len(t):
        raise ArgsError(x, t, _dict)
    for attr, value in _dict.items():
        try:
            typehint = t[attr]
        except KeyError:
            raise ArgsError(x, t, _dict)
        rtn = typecheck_single(value, typehint, cast)
        if cast and rtn is not None:
            x[attr] = rtn
