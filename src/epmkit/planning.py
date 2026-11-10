"""Planning REST API: jobs, substitution variables and data slices."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from .jobs import Job, JobStatus, app_path

if TYPE_CHECKING:
    import pandas as pd

    from .client import EPMClient

Members = str | Sequence[str]


def _as_list(members: Members) -> list[str]:
    return [members] if isinstance(members, str) else list(members)


def _axis(spec: Mapping[str, Members]) -> dict[str, Any]:
    return {"dimensions": list(spec), "members": [_as_list(m) for m in spec.values()]}


def _to_float(value: Any) -> float:
    """EPM sends '#Missing' (or other '#...' markers) for empty cells."""
    if value is None or value == "" or (isinstance(value, str) and value.startswith("#")):
        return math.nan
    return float(value)


class Planning:
    """``epm.planning``: operations on a Planning / FCCS / PCM application."""

    def __init__(self, client: EPMClient) -> None:
        self._client = client

    # -- jobs ----------------------------------------------------------------
    def run_job(self, app: str, job_type: str, job_name: str, parameters: Mapping[str, Any] | None = None) -> Job:
        """Start any Planning job. Returns immediately; call ``.wait()`` on the result."""
        payload = {
            "jobType": job_type,
            "jobName": job_name,
            "parameters": {k: str(v) for k, v in (parameters or {}).items()},
        }
        data = self._client.request("POST", f"{app_path(app)}/jobs", json=payload)
        return Job(self._client, app, JobStatus.model_validate(data), name=job_name)

    def run_rule(self, app: str, rule: str, **runtime_prompts: Any) -> Job:
        """Launch a business rule; keyword arguments become runtime prompt values."""
        return self.run_job(app, "RULES", rule, runtime_prompts)

    def import_data(self, app: str, job_name: str, file_name: str | None = None) -> Job:
        """Run an 'Import Data' job, optionally overriding the file it reads."""
        params = {"importFileName": file_name} if file_name else {}
        return self.run_job(app, "IMPORT_DATA", job_name, params)

    def get_job(self, app: str, job_id: int) -> Job:
        data = self._client.request("GET", f"{app_path(app)}/jobs/{job_id}")
        return Job(self._client, app, JobStatus.model_validate(data))

    # -- substitution variables ---------------------------------------------
    def get_subvars(self, app: str) -> dict[str, str]:
        data = self._client.request("GET", f"{app_path(app)}/substitutionvariables")
        return {item["name"]: item["value"] for item in (data or {}).get("items", [])}

    def set_subvar(self, app: str, name: str, value: str, plan_type: str = "ALL") -> None:
        body = {"items": [{"name": name, "value": value, "planType": plan_type}]}
        self._client.request("POST", f"{app_path(app)}/substitutionvariables", json=body)

    # -- data ------------------------------------------------------------------
    def export_slice(
        self,
        app: str,
        cube: str,
        *,
        pov: Mapping[str, Members],
        rows: Mapping[str, Members],
        cols: Mapping[str, Members],
        suppress_missing_rows: bool = False,
    ) -> pd.DataFrame:
        """Read a grid of data into a DataFrame (rows x cols, '#Missing' -> NaN)."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover - depends on install
            raise ImportError("export_slice needs pandas: pip install 'epmkit[pandas]'") from exc

        body = {
            "exportPlanningData": False,
            "gridDefinition": {
                "suppressMissingBlocks": True,
                "suppressMissingRows": suppress_missing_rows,
                "pov": _axis(pov),
                "rows": [_axis(rows)],
                "columns": [_axis(cols)],
            },
        }
        path = f"{app_path(app)}/plantypes/{quote(cube, safe='')}/exportdataslice"
        data = self._client.request("POST", path, json=body)

        col_tuples = list(zip(*data.get("columns", [])))
        row_tuples = [tuple(r["headers"]) for r in data.get("rows", [])]
        values = [[_to_float(v) for v in r["data"]] for r in data.get("rows", [])]
        return pd.DataFrame(
            values,
            index=_make_index(pd, row_tuples, list(rows)),
            columns=_make_index(pd, col_tuples, list(cols)),
        )


def _make_index(pd: Any, tuples: list[tuple[str, ...]], names: list[str]) -> Any:
    if len(names) == 1:
        return pd.Index([t[0] for t in tuples], name=names[0])
    return pd.MultiIndex.from_tuples(tuples, names=names)
