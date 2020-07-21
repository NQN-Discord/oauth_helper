from typing import GenericMeta, Any, NoReturn, Type, Dict, List, Set, Optional, Collection
import json
from collections import namedtuple

from oauth_helper import HTTPError
from .exceptions import TypeCheckError, CastError, ArgsError


async def get_params(request, annotations):
    if request.method in {"POST", "PUT", "DELETE"}:
        try:
            query = await request.json()
        except json.decoder.JSONDecodeError:
            raise HTTPError(status=400,
                            message="Invalid JSON")
    else:
        query = {}
        for key in request.rel_url.query.keys():
            if key.endswith("[]"):
                query[key.rstrip("[]")] = request.rel_url.query.getall(key)
            else:
                query[key] = request.rel_url.query.get(key)
    try:
        typecheck_class(query, annotations, cast=True)
    except CastError as e:
        raise HTTPError(status=400,
                        message=f"{e.value} was not of type `{e.type.__name__}`")
    except ArgsError as e:
        raise HTTPError(status=400,
                        message="Invalid parameters passed",
                        model=e.model,
                        expected=e.expected,
                        got=e.got)
    rtn_type = namedtuple("RequestQuery", query.keys())
    return rtn_type(**query)


def is_namedtuple(x: Any) -> bool:
    try:
        return tuple in x.__bases__ and hasattr(x, '_fields')
    except AttributeError:
        return False


def typecheck_single(x: Any, t: Type, cast: bool = False) -> Optional[Any]:
    if t is Any:
        return
    if isinstance(t, GenericMeta):
        if x == "":
            return []
        if t.__origin__ is List:
            return typecheck_collection(x, t, list)
        if t.__origin__ is Set:
            return typecheck_collection(x, t, (set, list)) # Special case these for deserialising being crap
        if t.__origin__ is Dict:
            return typecheck_dict(x, t)
    elif str(type(t)) == "typing.Union":
        for t2 in t.__args__:
            try:
                return typecheck_single(x, t2, cast)
            except TypeCheckError:
                pass
        raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
    elif is_namedtuple(t):
        return typecheck_class(x, t.__annotations__)
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
        return
    raise NotImplementedError(f"Unable to find type of variable: {type(x)}: {t}")


def typecheck_collection(x: Collection[Any], t: Type, correct: Type) -> NoReturn:
    of, = t.__args__
    if not isinstance(x, correct):
        raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
    for i in x:
        typecheck_single(i, of)


def typecheck_dict(x: Dict[Any, Any], t: Type) -> NoReturn:
    keys, values = t.__args__
    if not isinstance(x, dict):
        raise TypeCheckError(f"Typecheck failure: {t}, given {type(x)} ({x!r})")
    for k, v in x.items():
        typecheck_single(k, keys)
        typecheck_single(v, values)


def typecheck_class(x: Any, t: Dict[str, Type], cast: bool = False) -> NoReturn:
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
