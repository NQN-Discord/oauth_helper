import pytest
from collections import namedtuple
from typing import Union, List, Dict, Any, Optional, NamedTuple

from oauth_helper.exceptions import TypeCheckError, ArgsError
from oauth_helper.get_params import (
    is_namedtuple,
    typecheck_single,
    typecheck_collection,
)


test_named_tuple = namedtuple("test", ("a", "b"))


class AnnotatedNamedTuple(NamedTuple):
    foo: int
    bar: str


def test_is_namedtuple():
    assert is_namedtuple(test_named_tuple) is True
    assert is_namedtuple(()) is False
    assert is_namedtuple("") is False
    assert is_namedtuple({}) is False


def test_collection_unhappy():
    with pytest.raises(TypeCheckError) as e:
        typecheck_collection("", List[int], list)
    assert e.type is TypeCheckError
    assert (
        e.value.args[0]
        == "Typecheck failure: typing.List[int], given <class 'str'> ('')"
    )


def test_single_happy():
    typecheck_single(1, int)
    typecheck_single("", str)
    assert typecheck_single("1", int, cast=True) == 1


def test_single_unhappy():
    with pytest.raises(TypeCheckError) as e:
        typecheck_single(5, str)
    assert e.type is TypeCheckError
    assert (
        e.value.args[0] == "Typecheck failure: <class 'str'>, given <class 'int'> (5)"
    )


def test_list_happy():
    typecheck_single([1, 2, 3], List[int])
    typecheck_single(["", "foo", "bar"], List[str])
    typecheck_single([[1], [], [2, 3]], List[List[int]])
    assert typecheck_single("", List[int]) == []


def test_list_unhappy():
    with pytest.raises(TypeCheckError) as e:
        typecheck_single([1, 2, 3], List[str])
    with pytest.raises(TypeCheckError):
        typecheck_single([[1], [[]], [2, 3]], List[List[int]])


def test_dict_happy():
    typecheck_single({}, Dict)
    typecheck_single({1: ""}, Dict[int, str])
    typecheck_single({1: ""}, Dict[int, Any])
    typecheck_single({1: "", 2: 4}, Dict[int, Union[int, str]])
    typecheck_single({"": 2}, Dict[str, int])


def test_dict_unhappy():
    with pytest.raises(TypeCheckError):
        typecheck_single({2: [1]}, Dict[int, int])


def test_union_happy():
    typecheck_single(1, Union[int, str])
    typecheck_single("1", Union[int, str])


def test_union_unhappy():
    with pytest.raises(TypeCheckError):
        typecheck_single("", Union[int, None])


def test_optional_happy():
    typecheck_single(1, Optional[int])
    typecheck_single(None, Optional[int])
    typecheck_single({"": None}, Dict[str, Optional[int]])
    typecheck_single({"": 3}, Dict[str, Optional[int]])
    typecheck_single({None: None}, Dict[Optional[str], Optional[int]])


def test_optional_unhappy():
    with pytest.raises(TypeCheckError):
        typecheck_single("", Optional[int])


def test_namedtuple_happy():
    typecheck_single({"foo": 1, "bar": ""}, AnnotatedNamedTuple)


def test_namedtuple_unhappy():
    with pytest.raises(TypeCheckError):
        typecheck_single({"foo": 1, "bar": 2}, AnnotatedNamedTuple)
    with pytest.raises(TypeCheckError):
        typecheck_single({"foo": 1, "bar": []}, AnnotatedNamedTuple)
    with pytest.raises(ArgsError):
        typecheck_single({"foo": 1}, AnnotatedNamedTuple)
