"""Multi-step business workflows built on the low-level API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .client import EPMClient


def month_end_refresh(
    epm: EPMClient,
    app: str,
    local_file: str | Path,
    *,
    import_job: str,
    rule: str,
    timeout: float = 1800.0,
    log: Callable[[str], None] = print,
) -> None:
    """Upload actuals, load them, then aggregate.

    Each step waits for the previous one; any failure raises and stops the
    chain, so a bad load never gets aggregated. ``log`` defaults to ``print``
    but can be ``logger.info`` or a test spy.
    """
    name = Path(local_file).name

    log(f"[1/4] Uploading {name}")
    epm.files.upload(local_file)

    log(f"[2/4] Importing {name} with job {import_job}")
    epm.planning.import_data(app, import_job, name).wait(timeout)

    log(f"[3/4] Running rule {rule}")
    epm.planning.run_rule(app, rule).wait(timeout)

    log(f"[4/4] Month-end refresh of {app} complete")
