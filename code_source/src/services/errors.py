"""Errors raised by the services, independent of HTTP.

Each error carries a user-facing message and a machine `code` that the web pages test
(e.g. "already_paid"). The API maps each class to an HTTP status (api.responses).
"""


class ServiceError(Exception):
    code = "error"

    def __init__(self, message: str, code: str = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code


class NotFound(ServiceError):
    code = "not_found"


class InvalidRequest(ServiceError):
    """Input that passes the schema but breaks a business rule."""
    code = "invalid"


class Conflict(ServiceError):
    """The current state of the data forbids the action (paid, already linked, concurrent write)."""
    code = "conflict"


class StorageUnavailable(ServiceError):
    code = "unavailable"
