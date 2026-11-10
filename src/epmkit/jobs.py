"""Asynchronous EPM jobs (rules, data imports, ...) and how to wait for them.

EPM starts a job and returns immediately with ``status = -1``. The caller
polls ``GET .../jobs/{id}`` until the status changes. Status codes:
-1 running, 0 success, 1 error, 2 cancel pending, 3 cancelled, 4 invalid parameter.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from .exceptions import EPMJobFailed, EPMJobTimeout

if TYPE_CHECKING:
    from .client import EPMClient

PLANNING_APPS = "/HyperionPlanning/rest/v3/applications"
SUCCESS = 0
PENDING_STATUSES = frozenset({-1, 2})


def app_path(app: str) -> str:
    return f"{PLANNING_APPS}/{quote(app, safe='')}"


class JobStatus(BaseModel):
    """The job payload returned by the Planning jobs endpoint."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    job_id: int = Field(alias="jobId")
    job_name: str = Field(default="", alias="jobName")
    status: int
    descriptive_status: str = Field(default="", alias="descriptiveStatus")
    details: str | None = None


class Job:
    """Handle to a running or finished job."""

    def __init__(self, client: EPMClient, app: str, state: JobStatus, name: str | None = None) -> None:
        self._client = client
        self.app = app
        self._state = state
        self._name = name or state.job_name

    # -- state ---------------------------------------------------------------
    @property
    def id(self) -> int:
        return self._state.job_id

    @property
    def name(self) -> str:
        return self._state.job_name or self._name

    @property
    def status(self) -> int:
        return self._state.status

    @property
    def descriptive_status(self) -> str:
        return self._state.descriptive_status

    @property
    def details(self) -> str | None:
        return self._state.details

    @property
    def is_done(self) -> bool:
        return self.status not in PENDING_STATUSES

    @property
    def succeeded(self) -> bool:
        return self.status == SUCCESS

    # -- actions -------------------------------------------------------------
    def refresh(self) -> Job:
        data = self._client.request("GET", f"{app_path(self.app)}/jobs/{self.id}")
        self._state = JobStatus.model_validate(data)
        return self

    def wait(
        self,
        timeout: float = 600.0,
        *,
        initial_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff: float = 1.5,
        raise_on_error: bool = True,
    ) -> Job:
        """Poll until the job finishes, backing off exponentially between polls.

        Raises ``EPMJobTimeout`` if it is still running after ``timeout`` seconds,
        and ``EPMJobFailed`` if it ends unsuccessfully (unless ``raise_on_error=False``).
        """
        deadline = time.monotonic() + timeout
        delay = initial_delay
        while True:
            remaining = deadline - time.monotonic()
            if delay > 0 and remaining > 0:
                time.sleep(min(delay, remaining))
            self.refresh()
            if self.is_done:
                break
            if time.monotonic() >= deadline:
                raise EPMJobTimeout(self, timeout)
            delay = min(max(delay, 0.1) * backoff, max_delay)

        if raise_on_error and not self.succeeded:
            raise EPMJobFailed(self)
        return self

    def __repr__(self) -> str:
        return f"Job(id={self.id}, name={self.name!r}, status={self.descriptive_status!r})"
