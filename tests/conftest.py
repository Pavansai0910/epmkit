"""Shared fixtures: an EPMClient whose HTTP traffic is intercepted by respx.

No server is needed; each test declares exactly the responses it expects.
"""

import pytest
import respx

from epmkit import EPMClient

BASE_URL = "https://epm.test"
JOBS = "/HyperionPlanning/rest/v3/applications/Plan1/jobs"


@pytest.fixture
def mock_api():
    with respx.mock(base_url=BASE_URL, assert_all_called=True) as router:
        yield router


@pytest.fixture
def client(mock_api):
    with EPMClient(BASE_URL, "user", "secret", max_retries=0) as epm:
        yield epm


def job_payload(status: int, desc: str, details: str | None = None, job_id: int = 7, name: str = "AggAll"):
    return {"jobId": job_id, "jobName": name, "status": status, "descriptiveStatus": desc, "details": details}
