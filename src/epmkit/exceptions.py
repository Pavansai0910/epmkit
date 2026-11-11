"""Exception hierarchy for epmkit.

Every error the library raises derives from ``EPMError`` so callers can catch
one type, or a narrower one when they care about the cause.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .jobs import Job


class EPMError(Exception):
    """Base class for every error raised by epmkit."""

    def __init__(self, message: str, *, status_code: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class EPMAuthError(EPMError):
    """The server rejected the credentials (HTTP 401 or 403)."""


class EPMNotFound(EPMError):
    """The application, cube, job or file does not exist (HTTP 404)."""


class EPMJobFailed(EPMError):
    """A job finished, but not successfully (error, cancelled, invalid parameters)."""

    def __init__(self, job: Job) -> None:
        message = f"Job {job.id} ({job.name}) ended with status '{job.descriptive_status}'"
        if job.details:
            message += f": {job.details}"
        super().__init__(message)
        self.job = job


class EPMJobTimeout(EPMError):
    """A job was still running when ``Job.wait`` ran out of time."""

    def __init__(self, job: Job, timeout: float) -> None:
        super().__init__(
            f"Job {job.id} ({job.name}) still '{job.descriptive_status}' after {timeout:g}s"
        )
        self.job = job
        self.timeout = timeout
