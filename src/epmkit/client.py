"""The EPMClient: one HTTP session, error mapping, retries, and API namespaces."""

from __future__ import annotations

import time
from types import TracebackType
from typing import Any

import httpx

from .auth import basic_auth
from .exceptions import EPMAuthError, EPMError, EPMNotFound
from .files import Files
from .planning import Planning

# Only methods that are safe to repeat are retried on 5xx / network errors.
# POST (e.g. "start a rule") is retried only on 429, where the server
# guarantees it did not process the request.
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"})
RETRY_STATUSES = frozenset({429, 502, 503, 504})


class EPMClient:
    """Client for an Oracle EPM Cloud pod.

    >>> with EPMClient("https://my-pod.oraclecloud.com", "user", "pw") as epm:
    ...     epm.planning.run_rule("Plan1", "AggAll").wait()
    """

    def __init__(
        self,
        base_url: str,
        username: str | None = None,
        password: str | None = None,
        *,
        identity_domain: str | None = None,
        auth: httpx.Auth | None = None,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if auth is None:
            if not username or password is None:
                raise ValueError("Provide username and password, or pass auth=")
            auth = basic_auth(username, password, identity_domain)
        self.max_retries = max_retries
        self.backoff = backoff
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=auth,
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "User-Agent": "epmkit/0.1.0"},
        )
        self.planning = Planning(self)
        self.files = Files(self)

    # -- core request ------------------------------------------------------
    def request(self, method: str, path: str, *, raw: bool = False, **kwargs: Any) -> Any:
        """Send a request; return parsed JSON (or the Response if ``raw``).

        Raises ``EPMAuthError`` on 401/403 and ``EPMError`` on other failures.
        """
        method = method.upper()
        idempotent = method in IDEMPOTENT_METHODS
        attempt = 0
        while True:
            try:
                response = self._http.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if idempotent and attempt < self.max_retries:
                    self._pause(attempt)
                    attempt += 1
                    continue
                raise EPMError(f"{method} {path} failed: {exc}") from exc

            retryable = idempotent or response.status_code == 429
            if response.status_code in RETRY_STATUSES and retryable and attempt < self.max_retries:
                self._pause(attempt, response)
                attempt += 1
                continue
            break

        if response.status_code in (401, 403):
            raise EPMAuthError(
                f"Authentication failed (HTTP {response.status_code})",
                status_code=response.status_code,
                body=response.text,
            )
        if response.is_error:
            body = _body(response)
            error_cls = EPMNotFound if response.status_code == 404 else EPMError
            raise error_cls(
                f"{method} {path} -> HTTP {response.status_code}: {_detail(body)}",
                status_code=response.status_code,
                body=body,
            )
        if raw:
            return response
        return _body(response)

    def _pause(self, attempt: int, response: httpx.Response | None = None) -> None:
        retry_after = response.headers.get("Retry-After") if response is not None else None
        try:
            delay = float(retry_after) if retry_after else self.backoff * 2**attempt
        except ValueError:
            delay = self.backoff * 2**attempt
        time.sleep(delay)

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EPMClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def _body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def _detail(body: Any) -> str:
    if isinstance(body, dict):
        for key in ("detail", "details", "message", "error"):
            if body.get(key):
                return str(body[key])
    return str(body)[:500]
