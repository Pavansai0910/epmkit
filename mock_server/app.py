"""In-memory mock of the Oracle EPM Cloud REST endpoints epmkit uses.

Run:  uv run uvicorn mock_server.app:app --port 8000   (login demo / demo)

Behaviour worth knowing:
- Jobs report "Processing" for JOB_SECONDS, then finish, so clients must poll.
- Rule "FailRule" always fails; IMPORT_DATA fails if its file was not uploaded.
- export slices return '#Missing' for Opex/Mar to exercise NaN handling.
"""

from __future__ import annotations

import itertools
import json
import secrets
import time
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

USER, PASSWORD = "demo", "demo"
JOB_SECONDS = 0.5
APPS = {"Plan1"}
CUBES = {"OEP_FS", "OEP_WFP"}
JOB_TYPES = {"RULES", "IMPORT_DATA", "EXPORT_DATA", "CUBE_REFRESH"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
BASE_AMOUNTS = {"Revenue": 120000.0, "COGS": 70000.0, "Opex": 25000.0}

PLANNING = "/HyperionPlanning/rest/v3/applications/{app}"
INTEROP = "/interop/rest/11.1.2.3.600/applicationsnapshots"

security = HTTPBasic()


def require_auth(creds: HTTPBasicCredentials = Depends(security)) -> None:
    ok = secrets.compare_digest(creds.username, USER) & secrets.compare_digest(creds.password, PASSWORD)
    if not ok:
        raise HTTPException(401, "Invalid credentials", headers={"WWW-Authenticate": "Basic"})


app = FastAPI(title="Mock Oracle EPM Cloud", dependencies=[Depends(require_auth)])

# ---- in-memory state --------------------------------------------------------
_job_ids = itertools.count(1)
jobs: dict[int, dict[str, Any]] = {}
subvars: dict[str, dict[str, str]] = {"Plan1": {"CurYear": "FY26", "CurMonth": "Oct"}}
files: dict[str, dict[str, Any]] = {"Artifact Snapshot": {"type": "LCM", "content": bytearray()}}


def _check_app(name: str) -> None:
    if name not in APPS:
        raise HTTPException(404, f"Application {name} not found")


# ---- jobs -------------------------------------------------------------------
class JobRequest(BaseModel):
    jobType: str
    jobName: str
    parameters: dict[str, Any] = Field(default_factory=dict)


def _outcome(req: JobRequest) -> tuple[int, str, str | None]:
    if req.jobType == "RULES" and req.jobName == "FailRule":
        return 1, "Error", "Rule FailRule failed: member [Bogus] not found in dimension Entity"
    if req.jobType == "IMPORT_DATA":
        name = req.parameters.get("importFileName")
        if name and name not in files:
            return 1, "Error", f"File {name} not found in inbox"
    return 0, "Completed", None


def _job_view(app_name: str, job: dict[str, Any]) -> dict[str, Any]:
    if time.monotonic() < job["finish_at"]:
        status, desc, details = -1, "Processing", None
    else:
        status, desc, details = job["outcome"]
    href = f"{PLANNING.format(app=app_name)}/jobs/{job['id']}"
    return {
        "jobId": job["id"],
        "jobName": job["name"],
        "status": status,
        "descriptiveStatus": desc,
        "details": details,
        "links": [{"rel": "self", "href": href, "method": "GET"}],
    }


@app.post(PLANNING + "/jobs")
def start_job(app: str, req: JobRequest) -> dict[str, Any]:
    _check_app(app)
    if req.jobType not in JOB_TYPES:
        raise HTTPException(400, f"Unsupported jobType {req.jobType}")
    job_id = next(_job_ids)
    jobs[job_id] = {
        "id": job_id,
        "app": app,
        "name": req.jobName,
        "finish_at": time.monotonic() + JOB_SECONDS,
        "outcome": _outcome(req),
    }
    return _job_view(app, jobs[job_id])


@app.get(PLANNING + "/jobs/{job_id}")
def get_job(app: str, job_id: int) -> dict[str, Any]:
    _check_app(app)
    job = jobs.get(job_id)
    if job is None or job["app"] != app:
        raise HTTPException(404, f"Job {job_id} not found")
    return _job_view(app, job)


# ---- substitution variables -------------------------------------------------
@app.get(PLANNING + "/substitutionvariables")
def list_subvars(app: str) -> dict[str, Any]:
    _check_app(app)
    items = [{"name": k, "value": v, "planType": "ALL"} for k, v in subvars[app].items()]
    return {"items": items}


@app.post(PLANNING + "/substitutionvariables")
def set_subvars(app: str, body: dict[str, Any]) -> dict[str, Any]:
    _check_app(app)
    for item in body.get("items", []):
        subvars[app][item["name"]] = str(item["value"])
    return list_subvars(app)


# ---- data slices --------------------------------------------------------------
def _cell(members: tuple[str, ...]) -> float | str:
    if "Opex" in members and "Mar" in members:
        return "#Missing"
    account = next((m for m in members if m in BASE_AMOUNTS), None)
    month = next((MONTHS.index(m) for m in members if m in MONTHS), 0)
    return round(BASE_AMOUNTS.get(account, 1000.0) * (1 + 0.05 * month), 2)


@app.post(PLANNING + "/plantypes/{cube}/exportdataslice")
def export_slice(app: str, cube: str, body: dict[str, Any]) -> dict[str, Any]:
    _check_app(app)
    if cube not in CUBES:
        raise HTTPException(404, f"Cube {cube} not found in {app}")
    grid = body["gridDefinition"]
    pov = [m[0] for m in grid["pov"]["members"]]
    row_tuples = list(itertools.product(*grid["rows"][0]["members"]))
    col_tuples = list(itertools.product(*grid["columns"][0]["members"]))
    rows = [
        {"headers": list(r), "data": [_cell(tuple(pov) + r + c) for c in col_tuples]} for r in row_tuples
    ]
    return {"pov": pov, "columns": [list(level) for level in zip(*col_tuples)], "rows": rows}


# ---- files (interop / migration API) -----------------------------------------
@app.get(INTEROP)
def list_files() -> dict[str, Any]:
    items = [{"name": n, "type": f["type"]} for n, f in files.items()]
    return {"status": 0, "details": None, "items": items}


@app.post(INTEROP + "/{name}/contents")
async def upload_chunk(name: str, request: Request, q: str) -> dict[str, Any]:
    opts = json.loads(q)
    if opts.get("isFirst") or name not in files:
        files[name] = {"type": "EXTERNAL", "content": bytearray()}
    files[name]["content"] += await request.body()
    return {"status": 0, "details": None}


@app.get(INTEROP + "/{name}/contents")
def download_file(name: str) -> Response:
    if name not in files:
        raise HTTPException(404, f"File {name} not found")
    return Response(bytes(files[name]["content"]), media_type="application/octet-stream")


@app.delete(INTEROP + "/{name}")
def delete_file(name: str) -> dict[str, Any]:
    if files.pop(name, None) is None:
        return {"status": 8, "details": f"File {name} not found"}
    return {"status": 0, "details": None}
