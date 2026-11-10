"""Command-line interface. Connection settings come from EPM_URL, EPM_USER,
EPM_PASSWORD (and optionally EPM_DOMAIN) so secrets never appear in shell history.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import typer

from .client import EPMClient
from .exceptions import EPMError

app = typer.Typer(help="Command-line tools for Oracle EPM Cloud.", no_args_is_help=True)


def _connect() -> EPMClient:
    missing = [n for n in ("EPM_URL", "EPM_USER", "EPM_PASSWORD") if not os.environ.get(n)]
    if missing:
        typer.echo(f"Missing environment variables: {', '.join(missing)}", err=True)
        raise typer.Exit(2)
    return EPMClient(
        os.environ["EPM_URL"],
        os.environ["EPM_USER"],
        os.environ["EPM_PASSWORD"],
        identity_domain=os.environ.get("EPM_DOMAIN") or None,
    )


@contextmanager
def _session() -> Iterator[EPMClient]:
    """Open a client and turn library errors into a clean message + exit code 1."""
    try:
        with _connect() as epm:
            yield epm
    except EPMError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


def _parse_axis(specs: list[str], option: str) -> dict[str, list[str]]:
    axis: dict[str, list[str]] = {}
    for spec in specs:
        dim, sep, members = spec.partition("=")
        names = [m.strip() for m in members.split(",") if m.strip()]
        if not sep or not dim.strip() or not names:
            raise typer.BadParameter(f"expected Dim=Member[,Member...], got {spec!r}", param_hint=option)
        axis[dim.strip()] = names
    return axis


@app.command("run-rule")
def run_rule(
    application: str = typer.Argument(..., help="Application name, e.g. Plan1"),
    rule: str = typer.Argument(..., help="Business rule name"),
    wait: bool = typer.Option(True, "--wait/--no-wait", help="Wait for the job to finish"),
    timeout: float = typer.Option(600.0, help="Seconds to wait before giving up"),
) -> None:
    """Launch a business rule."""
    with _session() as epm:
        job = epm.planning.run_rule(application, rule)
        typer.echo(f"Started job {job.id} ({rule})")
        if wait:
            job.wait(timeout)
            typer.echo(job.descriptive_status)


@app.command()
def export(
    application: str = typer.Argument(..., help="Application name"),
    cube: str = typer.Argument(..., help="Cube / plan type, e.g. OEP_FS"),
    pov: list[str] = typer.Option(..., "--pov", help="Dim=Member, repeatable"),
    rows: list[str] = typer.Option(..., "--rows", help="Dim=M1,M2,..., repeatable"),
    cols: list[str] = typer.Option(..., "--cols", help="Dim=M1,M2,..., repeatable"),
    output: Path | None = typer.Option(None, "--output", "-o", help="Write CSV here instead of printing"),
) -> None:
    """Export a data slice."""
    with _session() as epm:
        df = epm.planning.export_slice(
            application,
            cube,
            pov=_parse_axis(pov, "--pov"),
            rows=_parse_axis(rows, "--rows"),
            cols=_parse_axis(cols, "--cols"),
        )
    if output:
        df.to_csv(output)
        typer.echo(f"Wrote {len(df)} rows to {output}")
    else:
        typer.echo(df.to_string())


@app.command("set-subvar")
def set_subvar(application: str, name: str, value: str) -> None:
    """Set a substitution variable."""
    with _session() as epm:
        epm.planning.set_subvar(application, name, value)
        typer.echo(f"{name} = {value}")


@app.command()
def upload(path: Path = typer.Argument(..., exists=True, dir_okay=False)) -> None:
    """Upload a file to the EPM inbox."""
    with _session() as epm:
        typer.echo(f"Uploaded {epm.files.upload(path)}")


@app.command("list-files")
def list_files() -> None:
    """List files in the EPM inbox/outbox."""
    with _session() as epm:
        for f in epm.files.list():
            typer.echo(f"{f.name}\t{f.type or ''}")
