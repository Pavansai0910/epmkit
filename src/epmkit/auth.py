"""Authentication helpers.

EPM Cloud accepts HTTP Basic auth (``identitydomain.username`` on classic
pods, plain ``username`` on OCI pods) and OAuth 2.0 bearer tokens. Both are
plain ``httpx.Auth`` objects, so any other httpx auth can be passed too.
"""

from __future__ import annotations

from collections.abc import Callable, Generator

import httpx


def basic_auth(username: str, password: str, identity_domain: str | None = None) -> httpx.BasicAuth:
    """Build Basic auth, prefixing the identity domain when one is given."""
    user = f"{identity_domain}.{username}" if identity_domain else username
    return httpx.BasicAuth(user, password)


class BearerAuth(httpx.Auth):
    """OAuth 2.0 bearer auth.

    Pass a token string, or a zero-argument callable that returns a current
    token so a token cache / refresh flow can be plugged in.
    """

    def __init__(self, token: str | Callable[[], str]) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        token = self._token() if callable(self._token) else self._token
        request.headers["Authorization"] = f"Bearer {token}"
        yield request
