from typing import Any, Type, Dict


class TypeCheckError(Exception):
    def __init__(self, message: str):
        super(TypeCheckError, self).__init__(message)


class CastError(TypeCheckError):
    def __init__(self, t: Type[Any], x: Any):
        super(CastError, self).__init__(f"Could not cast {x} to type {t}")
        self.type = t
        self.value = x


class ArgsError(TypeCheckError):
    def __init__(
        self, model: Any, expected: Dict[str, Type[Any]], got: Dict[str, Type[Any]]
    ):
        super(ArgsError, self).__init__(
            f"Could not construct {model.__class__.__name__}(**{expected}). Got {got}"
        )
        self.model = model.__class__.__name__
        self.expected = {k: getattr(v, "__name__", str(v)) for k, v in expected.items()}
        self.got = {k: getattr(v, "__name__", str(v)) for k, v in got.items()}
