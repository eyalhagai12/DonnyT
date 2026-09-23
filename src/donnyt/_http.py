"""Minimal JSON/HTTP client built on the standard library.

Deliberately dependency-free: this repo has to install and run inside an
isolated network where PyPI is unreachable, so the core talks HTTP with
``urllib`` rather than ``requests`` or ``httpx``.

Two things matter on a corporate internal network and are handled here:

* **TLS interception.** Many internal networks re-sign traffic with a private
  CA. Point ``DONNYT_CA_BUNDLE`` (or the conventional ``REQUESTS_CA_BUNDLE`` /
  ``SSL_CERT_FILE``) at the corporate root certificate and it is trusted.
* **Proxies.** ``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``NO_PROXY`` are honoured via
  urllib's standard proxy handling.
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_TIMEOUT = 30.0

_CA_BUNDLE_VARS = ("DONNYT_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE")


class HTTPError(RuntimeError):
    """An HTTP request returned a non-2xx status."""

    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} -> HTTP {status}: {body[:800]}")


def _ssl_context() -> ssl.SSLContext:
    """A TLS context honouring a corporate CA bundle if one is configured."""
    for var in _CA_BUNDLE_VARS:
        path = os.environ.get(var, "").strip()
        if path and os.path.exists(path):
            return ssl.create_default_context(cafile=path)

    if os.environ.get("DONNYT_INSECURE_TLS", "").strip().lower() in {"1", "true", "yes"}:
        # Escape hatch for a self-signed internal host when the CA file cannot
        # be obtained. Off by default and never silently enabled.
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    return ssl.create_default_context()


class JSONClient:
    """A small JSON-over-HTTP client with a fixed base URL and auth header."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "donnyt/0.1",
            **(headers or {}),
        }
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=_ssl_context()),
            urllib.request.ProxyHandler(),  # reads *_PROXY from the environment
        )

    @staticmethod
    def basic_auth(user: str, secret: str) -> dict[str, str]:
        raw = f"{user}:{secret}".encode()
        return {"Authorization": "Basic " + base64.b64encode(raw).decode()}

    @staticmethod
    def bearer(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        url = path if path.startswith("http") else f"{self.base_url}{path}"

        if params:
            # Drop None values; render bools the way REST APIs expect.
            clean = {
                k: ("true" if v is True else "false" if v is False else v)
                for k, v in params.items()
                if v is not None
            }
            if clean:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(clean, doseq=True)

        data = None
        headers = dict(self.headers)
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method.upper())

        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:  # non-2xx
            detail = exc.read().decode("utf-8", errors="replace")
            raise HTTPError(method.upper(), url, exc.code, detail) from None
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"Could not reach {url}: {exc.reason}. On an internal network check "
                "HTTPS_PROXY / NO_PROXY, and set DONNYT_CA_BUNDLE to your corporate "
                "root certificate if TLS is intercepted."
            ) from None

        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"_raw": body}

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self.request("PUT", path, **kwargs)
