"""Business-rule errors raised by services; the API turns them into HTTP responses (app/main.py)."""


class RuleError(Exception):
    status_code = 422


class NotFoundError(RuleError):
    """Missing or outside the caller's scope: the two look the same, so nothing leaks."""

    status_code = 404


class ForbiddenError(RuleError):
    status_code = 403


class InvalidError(RuleError):
    status_code = 422


class ConflictError(RuleError):
    status_code = 409
