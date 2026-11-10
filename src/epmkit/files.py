"""File transfer through the EPM Migration (interop) REST API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict

from .exceptions import EPMError

if TYPE_CHECKING:
    from .client import EPMClient

INTEROP = "/interop/rest/11.1.2.3.600/applicationsnapshots"
DEFAULT_CHUNK_SIZE = 50 * 1024 * 1024  # EPM accepts uploads in chunks of up to ~50 MB


class FileInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    type: str | None = None


def _check(data: Any, action: str) -> Any:
    """Interop calls return HTTP 200 with a body status; non-zero means failure."""
    if isinstance(data, dict) and data.get("status", 0) != 0:
        raise EPMError(f"{action} failed: {data.get('details') or data}", body=data)
    return data


def _contents_path(name: str) -> str:
    return f"{INTEROP}/{quote(name, safe='')}/contents"


class Files:
    """``epm.files``: list, upload, download and delete files in the EPM inbox."""

    def __init__(self, client: EPMClient) -> None:
        self._client = client

    def list(self) -> list[FileInfo]:
        data = _check(self._client.request("GET", INTEROP), "List files")
        return [FileInfo.model_validate(item) for item in data.get("items", [])]

    def upload(self, local_path: str | Path, remote_name: str | None = None, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
        """Upload a file in chunks; returns the name it was stored under."""
        path = Path(local_path)
        name = remote_name or path.name
        with path.open("rb") as fh:
            chunk = fh.read(chunk_size)
            is_first = True
            while True:
                following = fh.read(chunk_size)
                is_last = not following
                q = json.dumps({"isFirst": is_first, "isLast": is_last, "chunkSize": len(chunk)})
                data = self._client.request(
                    "POST",
                    _contents_path(name),
                    params={"q": q},
                    content=chunk,
                    headers={"Content-Type": "application/octet-stream"},
                )
                _check(data, f"Upload of {name}")
                if is_last:
                    return name
                chunk, is_first = following, False

    def download(self, name: str, dest: str | Path | None = None) -> Path:
        response = self._client.request("GET", _contents_path(name), raw=True)
        target = Path(dest) if dest else Path(name)
        if target.is_dir():
            target = target / name
        target.write_bytes(response.content)
        return target

    def delete(self, name: str) -> None:
        _check(self._client.request("DELETE", f"{INTEROP}/{quote(name, safe='')}"), f"Delete of {name}")
