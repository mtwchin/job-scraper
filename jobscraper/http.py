"""Shared requests session with sane defaults and light retry."""
from __future__ import annotations

import time

import requests

from . import settings

_session: requests.Session | None = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": settings.USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        _session = s
    return _session


def request(method: str, url: str, *, retries: int = 2, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", settings.REQUEST_TIMEOUT)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = session().request(method, url, **kwargs)
            # Retry on transient server / rate-limit responses.
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
    assert last_exc is not None  # unreachable
    raise last_exc


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)
