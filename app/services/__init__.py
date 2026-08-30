"""Service layer. Routes translate these errors into HTTP status codes so the
services stay free of FastAPI imports."""


class NotFound(LookupError):
    """No such row. -> 404"""


class Conflict(ValueError):
    """The request contradicts current state. -> 409"""


class Unavailable(RuntimeError):
    """A dependency this feature needs is missing or unreachable. -> 503"""
