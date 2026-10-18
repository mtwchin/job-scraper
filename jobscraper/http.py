"""HTTP helper with per-thread sessions, sane defaults, and light retry.

Sessions are thread-local because the scraper fetches companies concurrently and
requests.Session's connection pool is not safe to share across threads.
"""
from __future__ import annotations

import threading
import time

import requests

from . import settings

_local = threading.local()


def session() -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": settings.USER_AGENT,
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        _local.session = s
    return s


def request(method: str, url: str, *, retries: int = 2, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", settings.REQUEST_TIMEOUT)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = session().request(method, url, **kwargs)
            # Retry on transient server / rate-limit responses.
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(_retry_delay(resp, attempt))
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


def _retry_delay(resp: requests.Response, attempt: int) -> float:
    """Back off before a retry, honouring a short Retry-After when one is sent.

    Capped: a host asking for minutes is better left to the per-company backoff
    in main.py than allowed to hold a worker thread hostage.
    """
    default = 1.5 * (attempt + 1)
    try:
        return min(max(float(resp.headers.get("Retry-After", default)), default), 10.0)
    except (TypeError, ValueError):
        return default  # an HTTP-date, or garbage


class NotJSON(Exception):
    """A 2xx answer from a JSON API that isn't JSON.

    In practice this is a rate limiter or bot wall answering in the API's place:
    Workday, once it decides a runner IP is too busy, replies 200 with an empty
    body. Surfacing that as "JSONDecodeError: Expecting value" hid what was
    actually going on.
    """


def json_body(resp: requests.Response):
    """`resp.json()`, but a non-JSON body raises NotJSON with a readable reason."""
    try:
        return resp.json()
    except ValueError:  # requests' JSONDecodeError subclasses ValueError
        body = (getattr(resp, "text", "") or "").strip()
        headers = getattr(resp, "headers", None) or {}
        ctype = headers.get("Content-Type", "unknown type").split(";")[0]
        what = "an empty body" if not body else f"{ctype} {body[:60]!r}"
        status = getattr(resp, "status_code", "?")
        raise NotJSON(f"HTTP {status} with {what} instead of JSON "
                      "(likely rate-limited or bot-blocked)") from None


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)
