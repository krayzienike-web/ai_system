"""Business-rule errors raised by services; the API turns them into HTTP responses (app/main.py)."""


class RuleError(Exception):
    status_code = 422

    def __init__(self, message: str = "", *, code: str | None = None) -> None:
        """`code`: what the screen may act on, so it never reads the words (ADR 0007) — «no_header»: the file
        can be marked with the assistant."""
        super().__init__(message)
        self.code = code


class NotFoundError(RuleError):
    """Missing or outside the caller's scope: the two look the same, so nothing leaks."""

    status_code = 404


class ForbiddenError(RuleError):
    status_code = 403


class InvalidError(RuleError):
    status_code = 422


class ConflictError(RuleError):
    status_code = 409
