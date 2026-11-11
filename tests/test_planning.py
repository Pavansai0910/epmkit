import json
import math

import httpx
import pytest

from epmkit import EPMJobFailed, EPMJobTimeout, month_end_refresh

from .conftest import JOBS, job_payload

PLAN1 = "/HyperionPlanning/rest/v3/applications/Plan1"
EXPORT = f"{PLAN1}/plantypes/OEP_FS/exportdataslice"


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


def test_export_slice_builds_grid_and_maps_missing_to_nan(client, mock_api):
    route = mock_api.post(EXPORT).respond(
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


def test_get_subvars_returns_name_to_value_dict(client, mock_api):
    mock_api.get(f"{PLAN1}/substitutionvariables").respond(
        json={
            "items": [
                {"name": "CurYear", "value": "FY26", "planType": "ALL"},
                {"name": "CurMonth", "value": "Nov", "planType": "ALL"},
            ]
        }
    )

    assert client.planning.get_subvars("Plan1") == {"CurYear": "FY26", "CurMonth": "Nov"}


def test_empty_export_returns_empty_dataframe(client, mock_api):
    mock_api.post(EXPORT).respond(json={"pov": ["Actual", "FY26"], "columns": [["Jan", "Feb"]], "rows": []})

    df = client.planning.export_slice(
        "Plan1",
        "OEP_FS",
        pov={"Scenario": "Actual", "Year": "FY26"},
        rows={"Account": ["Revenue"]},
        cols={"Period": ["Jan", "Feb"]},
        suppress_missing_rows=True,
    )

    assert df.empty
    assert list(df.columns) == ["Jan", "Feb"]


def test_month_end_refresh_runs_upload_then_import_then_rule(client, mock_api, tmp_path, monkeypatch):
    monkeypatch.setattr("epmkit.jobs.time.sleep", lambda _seconds: None)  # no real waiting
    src = tmp_path / "actuals_nov.csv"
    src.write_text("Account,Period,Amount\n")
    mock_api.post("/interop/rest/11.1.2.3.600/applicationsnapshots/actuals_nov.csv/contents").respond(
        json={"status": 0}
    )
    mock_api.post(JOBS).mock(
        side_effect=[
            httpx.Response(200, json=job_payload(-1, "Processing", job_id=1, name="LoadActuals")),
            httpx.Response(200, json=job_payload(-1, "Processing", job_id=2, name="AggAll")),
        ]
    )
    mock_api.get(f"{JOBS}/1").respond(json=job_payload(0, "Completed", job_id=1, name="LoadActuals"))
    mock_api.get(f"{JOBS}/2").respond(json=job_payload(0, "Completed", job_id=2, name="AggAll"))
    log: list[str] = []

    month_end_refresh(client, "Plan1", src, import_job="LoadActuals", rule="AggAll", log=log.append)

    steps = []
    for call in mock_api.calls:
        req = call.request
        job_type = json.loads(req.content)["jobType"] if req.url.path == JOBS else None
        steps.append((req.method, req.url.path.rsplit("/", 1)[-1], job_type))
    assert steps == [
        ("POST", "contents", None),  # 1. upload
        ("POST", "jobs", "IMPORT_DATA"),  # 2. import starts...
        ("GET", "1", None),  # ...and is waited on
        ("POST", "jobs", "RULES"),  # 3. rule starts only after the import finished
        ("GET", "2", None),
    ]
    assert len(log) == 4 and log[-1].startswith("[4/4]")
