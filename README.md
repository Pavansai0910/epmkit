# epmkit

[![CI](https://github.com/Pavansai0910/epmkit/actions/workflows/ci.yml/badge.svg)](https://github.com/Pavansai0910/epmkit/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**Unofficial Python SDK for Oracle EPM Cloud REST APIs.** Run business rules, load data,
read data slices into pandas, manage substitution variables and move files, from Python
or the command line, with retries, typed errors and job polling built in.

> Not affiliated with or endorsed by Oracle. Endpoints and payloads follow Oracle's public
> REST API documentation and are tested against the bundled mock server, not a live pod.
> Validate against a test environment before relying on it in production.

## Why

Oracle EPM's REST API is powerful but low-level: long URLs, nested JSON grids, jobs that
run in the background and must be polled, and failures that sometimes arrive as HTTP 200.
epmkit turns that into a few lines of Python:

```python
epm.planning.run_rule("Plan1", "AggAll").wait()
```

## Install

Not on PyPI yet; install from GitHub:

```bash
pip install "epmkit[pandas,cli] @ git+https://github.com/Pavansai0910/epmkit"
```

Extras are optional: `pandas` is needed for `export_slice`, `cli` for the `epmkit` command.
The core only depends on `httpx` and `pydantic`.

## Quickstart

Start the mock server (from a clone, see [Development](#development)), then:

```python
from epmkit import EPMClient
from epmkit.exceptions import EPMJobFailed

with EPMClient("http://localhost:8000", "demo", "demo") as epm:
    # Start a business rule and wait for it (polls with exponential backoff)
    job = epm.planning.run_rule("Plan1", "AggAll").wait(timeout=600)
    print(job)  # Job(id=1, name='AggAll', status='Completed')

    # Substitution variables
    epm.planning.set_subvar("Plan1", "CurMonth", "Nov")
    print(epm.planning.get_subvars("Plan1"))  # {'CurYear': 'FY26', 'CurMonth': 'Nov'}

    # Read a grid of data into a DataFrame ('#Missing' becomes NaN)
    df = epm.planning.export_slice(
        "Plan1", "OEP_FS",
        pov={"Scenario": "Actual", "Year": "FY26"},
        rows={"Account": ["Revenue", "COGS"]},
        cols={"Period": ["Jan", "Feb", "Mar"]},
    )
    print(df)

    # Failures raise with Oracle's error details
    try:
        epm.planning.run_rule("Plan1", "FailRule").wait()
    except EPMJobFailed as exc:
        print("rule failed:", exc.job.details)
```

For a real pod, use its URL and your credentials. Classic pods need the identity domain:
`EPMClient(url, user, password, identity_domain="mydomain")`. For OAuth, pass
`auth=BearerAuth(token)` from `epmkit.auth`.

### Month-end in one call

```python
from epmkit import month_end_refresh

month_end_refresh(epm, "Plan1", "actuals_nov.csv", import_job="LoadActuals", rule="AggAll")
# [1/4] Uploading actuals_nov.csv
# [2/4] Importing actuals_nov.csv with job LoadActuals
# [3/4] Running rule AggAll
# [4/4] Month-end refresh of Plan1 complete
```

Each step waits for the previous one, and any failure stops the chain, so a bad load is
never aggregated.

## Command line

Credentials come from environment variables, so they never land in shell history.

PowerShell:

```powershell
$env:EPM_URL="http://localhost:8000"; $env:EPM_USER="demo"; $env:EPM_PASSWORD="demo"
epmkit run-rule Plan1 AggAll
epmkit export Plan1 OEP_FS --pov Scenario=Actual --pov Year=FY26 --rows Account=Revenue,COGS --cols Period=Jan,Feb -o slice.csv
epmkit set-subvar Plan1 CurMonth Nov
epmkit upload actuals_nov.csv
epmkit list-files
```

Optional: `EPM_DOMAIN` for classic pods. Exit codes: `0` success, `1` EPM error or failed
job, `2` missing configuration.

## What's covered

| Area | Methods |
|---|---|
| Jobs | `planning.run_rule`, `planning.import_data`, `planning.run_job`, `planning.get_job`, `Job.wait`, `Job.refresh` |
| Substitution variables | `planning.get_subvars`, `planning.set_subvar` |
| Data | `planning.export_slice` (to pandas DataFrame) |
| Files (interop API) | `files.list`, `files.upload` (chunked), `files.download`, `files.delete` |
| Workflows | `month_end_refresh` |

## Design

- **One request path.** Every call goes through `EPMClient.request`, which handles auth,
  retries and error mapping in one place; the API modules only describe endpoints.
- **Safe retries.** `GET`/`PUT`/`DELETE` are retried on 502/503/504 and network errors with
  exponential backoff (honouring `Retry-After`). `POST` is retried only on 429, because a
  POST starts a job and resubmitting after an ambiguous failure could run a rule twice.
- **Async jobs as objects.** `run_rule()` returns a `Job` immediately; `.wait()` polls with
  backoff (1s growing ×1.5 to 30s) under a hard timeout, so short jobs return fast and long
  ones don't hammer the server.
- **Typed errors.** `EPMError` → `EPMAuthError` (401/403), `EPMNotFound` (404),
  `EPMJobFailed` (carries the job and Oracle's details), `EPMJobTimeout`. Interop responses
  that report failure inside an HTTP 200 are raised too.
- **Missing is not zero.** `#Missing` cells become `NaN`, so "no data" stays distinct from 0.

## Development

```bash
git clone https://github.com/Pavansai0910/epmkit
cd epmkit
uv sync --all-extras
```

```bash
uv run uvicorn mock_server.app:app --port 8000
```

```bash
uv run python scripts/smoke.py
```

```bash
uv run pytest -q
```

```bash
uv run ruff check .
```

The mock server (`mock_server/app.py`, login `demo`/`demo`) imitates the EPM endpoints
epmkit uses: jobs stay "Processing" briefly so polling is exercised, `FailRule` always fails,
imports fail if the file wasn't uploaded, and Opex/Mar returns `#Missing`.

Unit tests use [respx](https://lundberg.github.io/respx/) to fake HTTP, so they need no
server. CI runs lint and tests on Python 3.10–3.13 plus an end-to-end smoke test against
the mock server.

## License

[MIT](LICENSE)
