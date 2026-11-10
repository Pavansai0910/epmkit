import json
import math

import httpx
import pytest

from epmkit import EPMAuthError, EPMJobFailed, EPMJobTimeout

from .conftest import JOBS, job_payload


def test_run_rule_sends_payload_and_polls_until_complete(client, mock_api):
    start = mock_api.post(JOBS).respond(json=job_payload(-1, "Processing"))
    poll = mock_api.get(f"{JOBS}/7").mock(
        side_effect=[
            httpx.Response(200, json=job_payload(-1, "Processing")),
            httpx.Response(200, json=job_payload(0, "Completed")),
        ]
    )

    job = client.planning.run_rule("Plan1", "AggAll", Entity="E100").wait(initial_delay=0)

    assert job.succeeded and job.descriptive_status == "Completed"
    assert poll.call_count == 2
    assert json.loads(start.calls.last.request.content) == {
        "jobType": "RULES",
        "jobName": "AggAll",
        "parameters": {"Entity": "E100"},
    }


def test_failed_job_raises_with_details(client, mock_api):
    mock_api.post(JOBS).respond(json=job_payload(-1, "Processing", name="FailRule"))
    mock_api.get(f"{JOBS}/7").respond(json=job_payload(1, "Error", "bad member", name="FailRule"))

    with pytest.raises(EPMJobFailed, match="bad member") as exc_info:
        client.planning.run_rule("Plan1", "FailRule").wait(initial_delay=0)
    assert exc_info.value.job.status == 1


def test_wait_times_out_while_job_still_running(client, mock_api):
    mock_api.post(JOBS).respond(json=job_payload(-1, "Processing"))
    mock_api.get(f"{JOBS}/7").respond(json=job_payload(-1, "Processing"))

    with pytest.raises(EPMJobTimeout):
        client.planning.run_rule("Plan1", "AggAll").wait(timeout=0)


def test_401_raises_auth_error_and_basic_auth_is_sent(client, mock_api):
    route = mock_api.post(JOBS).respond(401, text="Unauthorized")

    with pytest.raises(EPMAuthError):
        client.planning.run_rule("Plan1", "AggAll")
    assert route.calls.last.request.headers["Authorization"].startswith("Basic ")


def test_export_slice_builds_grid_and_maps_missing_to_nan(client, mock_api):
    route = mock_api.post("/HyperionPlanning/rest/v3/applications/Plan1/plantypes/OEP_FS/exportdataslice").respond(
        json={
            "pov": ["Actual", "FY26"],
            "columns": [["Jan", "Feb"]],
            "rows": [
                {"headers": ["Revenue"], "data": ["100", "110.5"]},
                {"headers": ["Opex"], "data": [40, "#Missing"]},
            ],
        }
    )

    df = client.planning.export_slice(
        "Plan1",
        "OEP_FS",
        pov={"Scenario": "Actual", "Year": "FY26"},
        rows={"Account": ["Revenue", "Opex"]},
        cols={"Period": ["Jan", "Feb"]},
    )

    grid = json.loads(route.calls.last.request.content)["gridDefinition"]
    assert grid["pov"] == {"dimensions": ["Scenario", "Year"], "members": [["Actual"], ["FY26"]]}
    assert grid["rows"] == [{"dimensions": ["Account"], "members": [["Revenue", "Opex"]]}]
    assert df.shape == (2, 2)
    assert df.loc["Revenue", "Feb"] == 110.5
    assert math.isnan(df.loc["Opex", "Feb"])
