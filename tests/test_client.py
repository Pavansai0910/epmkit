"""Client-level behaviour: error mapping and retry policy."""

import httpx
import pytest

from epmkit import EPMAuthError, EPMError
from epmkit.exceptions import EPMNotFound

from .conftest import JOBS, job_payload

SUBVARS = "/HyperionPlanning/rest/v3/applications/Plan1/substitutionvariables"


def test_401_raises_auth_error_and_basic_auth_is_sent(client, mock_api):
    route = mock_api.post(JOBS).respond(401, text="Unauthorized")

    with pytest.raises(EPMAuthError):
        client.planning.run_rule("Plan1", "AggAll")
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")


def test_404_raises_not_found_with_server_detail(client, mock_api):
    mock_api.get(f"{JOBS}/99").respond(404, json={"detail": "Job 99 not found"})

    with pytest.raises(EPMNotFound, match="Job 99 not found") as exc_info:
        client.planning.get_job("Plan1", 99)
    assert exc_info.value.status_code == 404
    assert isinstance(exc_info.value, EPMError)  # still catchable as the base error


def test_get_is_retried_on_503_then_succeeds(retrying_client, mock_api):
    route = mock_api.get(SUBVARS).mock(
        side_effect=[
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json={"items": [{"name": "CurMonth", "value": "Nov"}]}),
        ]
    )

    assert retrying_client.planning.get_subvars("Plan1") == {"CurMonth": "Nov"}
    assert route.call_count == 2


def test_post_is_not_retried_on_503(retrying_client, mock_api):
    route = mock_api.post(JOBS).respond(503, text="Service Unavailable")

    with pytest.raises(EPMError) as exc_info:
        retrying_client.planning.run_rule("Plan1", "AggAll")
    assert exc_info.value.status_code == 503
    assert route.call_count == 1  # never resubmit a job that may already be running


def test_post_is_retried_on_429(retrying_client, mock_api):
    route = mock_api.post(JOBS).mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json=job_payload(-1, "Processing")),
        ]
    )

    job = retrying_client.planning.run_rule("Plan1", "AggAll")
    assert job.id == 7
    assert route.call_count == 2
