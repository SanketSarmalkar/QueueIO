"""Shared HTTP plumbing for Yahoo Finance endpoints.

Provides a warmed-up session (cookie + crumb), host rotation across
query1/query2, and exponential backoff on 429/5xx. Everything is best-effort
and never raises to callers — failures come back as an error string.
"""

from __future__ import annotations

import threading
import time

import requests

_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_session: requests.Session | None = None
_crumb: str | None = None
_lock = threading.Lock()


def get_session() -> requests.Session:
    """Return a shared session, warming up Yahoo cookies once."""
    global _session
    if _session is not None:
        return _session
    with _lock:
        if _session is None:
            sess = requests.Session()
            sess.headers.update(_HEADERS)
            try:  # best-effort cookie warm-up
                sess.get("https://fc.yahoo.com", timeout=5)
            except requests.RequestException:
                pass
            _session = sess
    return _session


def get_crumb(*, timeout: float = 6.0) -> str | None:
    """Fetch (and cache) the Yahoo crumb needed by the v7/v10 endpoints."""
    global _crumb
    if _crumb is not None:
        return _crumb or None
    sess = get_session()
    with _lock:
        if _crumb is None:
            _crumb = ""  # cache the attempt even on failure to avoid re-hammering
            for host in _HOSTS:
                try:
                    r = sess.get(
                        f"https://{host}/v1/test/getcrumb", timeout=timeout
                    )
                    if r.status_code == 200 and r.text and "<" not in r.text:
                        _crumb = r.text.strip()
                        break
                except requests.RequestException:
                    continue
    return _crumb or None


def get_json(
    path: str,
    *,
    params: dict | None = None,
    timeout: float = 10.0,
    retries: int = 3,
):
    """GET a JSON path (e.g. ``/v8/finance/chart/AAPL``) with rotation + backoff.

    Returns ``(payload, None)`` on success or ``(None, error_str)`` on failure.
    """
    sess = get_session()
    last_err = "unknown error"
    for attempt in range(retries):
        host = _HOSTS[attempt % len(_HOSTS)]
        url = f"https://{host}{path}"
        try:
            resp = sess.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_err = f"network: {exc}"
            continue

        if resp.status_code in (429, 500, 502, 503, 504):
            last_err = f"http {resp.status_code} (rate-limited/busy)"
            retry_after = resp.headers.get("Retry-After")
            delay = (
                float(retry_after)
                if (retry_after or "").isdigit()
                else 0.8 * (2**attempt)
            )
            if attempt < retries - 1:
                time.sleep(min(delay, 5.0))
            continue

        try:
            resp.raise_for_status()
            return resp.json(), None
        except requests.RequestException as exc:
            return None, f"http {resp.status_code}"
        except ValueError as exc:
            return None, f"bad json: {exc}"
    return None, last_err
