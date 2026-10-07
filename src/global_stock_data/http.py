"""One policy-gated HTTP boundary; redirects and permission retries forbidden."""

import hashlib
import json
import logging
import math
import os
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import DataError, require
from .policy import PATHS, authorize

LOG = logging.getLogger(__name__)
MAX_BYTES = 20_000_000


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> Response: ...


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def _transport(url: str, headers: dict[str, str], timeout: float) -> Response:
    # Defense in depth for direct callers: transport cannot reach an unapproved route.
    provider = next(
        (
            name
            for name, routes in PATHS.items()
            if any(urlsplit(url).hostname == host for host, _ in routes)
        ),
        "unknown",
    )
    authorize(provider, url, online=True)
    require(
        provider != "sec" or "@" in headers.get("User-Agent", ""),
        "Declared SEC agent required",
        "config",
    )
    try:
        # URL already constrained to reviewed HTTPS host/path; proxy redirects are not followed.
        with build_opener(NoRedirect()).open(
            Request(url, headers=headers),  # noqa: S310 - policy-gated HTTPS only
            timeout=timeout,  # noqa: S310 - policy-gated HTTPS only
        ) as reply:  # noqa: S310
            body = reply.read(MAX_BYTES + 1)
            require(len(body) <= MAX_BYTES, "Response exceeds size limit")
            return Response(reply.status, {k.lower(): v for k, v in reply.headers.items()}, body)
    except HTTPError as exc:
        return Response(exc.code, {k.lower(): v for k, v in exc.headers.items()}, b"")
    except (TimeoutError, OSError, URLError) as exc:
        raise DataError(
            "timeout"
            if isinstance(exc, TimeoutError)
            or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError))
            else "network",
            "Transport failed; request details redacted",
        ) from exc


class SharedBudget:
    """SQLite sliding window shared by processes using ONE canonical local path.

    This is not a cross-host/IP coordinator. All SEC workloads behind the same
    egress must use this budget, or a single network gateway. Do not run this
    beside independent downloaders or on network filesystems.
    """

    def __init__(self, path: Path, limit: int = 8, window: float = 1.0) -> None:
        require(1 <= limit <= 8 and window >= 1, "Budget must not exceed safe local SEC rate")
        self.path, self.limit, self.window = path, limit, window
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (at REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS cooldown (until REAL NOT NULL)")
        os.chmod(path, 0o600)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30, isolation_level=None)

    def reserve(self, now: float) -> float:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM requests WHERE at <= ?", (now - self.window,))
            cooldown = db.execute("SELECT MAX(until) FROM cooldown").fetchone()[0] or 0
            rows = db.execute("SELECT at FROM requests ORDER BY at").fetchall()
            delay = max(0.0, cooldown - now)
            if len(rows) >= self.limit:
                delay = max(delay, rows[0][0] + self.window - now)
            if delay <= 0:
                db.execute("INSERT INTO requests VALUES (?)", (now,))
            db.commit()
        return float(delay)

    def acquire(
        self, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        started = clock()
        while (delay := self.reserve(clock())) > 0:
            if delay > 60 or clock() - started + delay > 60:
                raise DataError("rate_limited", "Shared budget wait exceeds bounded execution time")
            sleep(delay)

    def defer(self, until: float) -> None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT MAX(until) FROM cooldown").fetchone()[0] or 0
            db.execute("DELETE FROM cooldown")
            db.execute("INSERT INTO cooldown VALUES (?)", (max(previous, until),))
            db.commit()


@dataclass(frozen=True)
class Payload:
    body: bytes
    fetched_at: str
    evidence_ref: str
    cached: bool

    def json(self) -> Any:
        try:
            return json.loads(
                self.body, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise DataError("schema", "Response is not valid JSON") from exc


class Client:
    def __init__(
        self,
        state_dir: Path,
        *,
        online: bool = False,
        sec_contact: str | None = None,
        sender: Transport = _transport,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.online, self.sec_contact = online, sec_contact
        self.sender, self.clock, self.sleep = sender, clock, sleep
        self.state_dir = state_dir
        self.cache_path = state_dir / "cache.sqlite"

    def initialize(self, provider: str) -> SharedBudget:
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        budget = SharedBudget(
            self.state_dir / (provider + "-budget.sqlite"), limit=8 if provider == "sec" else 1
        )
        with sqlite3.connect(self.cache_path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, body BLOB, fetched REAL)"
            )
            db.execute("DELETE FROM cache WHERE fetched < ?", (self.clock() - 86400,))
        os.chmod(self.cache_path, 0o600)
        return budget

    def get(
        self,
        provider: str,
        url: str,
        *,
        ttl: float = 300,
        max_age: float = 300,
        timeout: float = 15,
        attempts: int = 3,
    ) -> Payload:
        authorize(provider, url, online=self.online)
        require(
            all(math.isfinite(x) for x in (ttl, max_age, timeout))
            and 0 <= ttl <= 86400
            and 0 <= max_age <= 86400
            and 0 < timeout <= 60
            and 1 <= attempts <= 3,
            "Invalid request budget",
            "config",
        )
        headers = {
            "User-Agent": "global-stock-data/3.0.0",
            "Accept": "application/json, text/plain, application/xml",
        }
        if provider == "sec":
            contact: str = self.sec_contact or os.environ.get("SEC_CONTACT", "") or ""
            require(
                bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", contact))
                and not any(
                    s in contact.lower()
                    for s in (
                        "example.",
                        "placeholder",
                        "your@",
                        "contact@domain",
                        ".invalid",
                        ".test",
                        ".localhost",
                    )
                ),
                "SEC_CONTACT must be an explicitly configured real contact",
                "config",
            )
            headers["User-Agent"] += " " + contact
        budget = self.initialize(provider)
        key = hashlib.sha256(url.encode()).hexdigest()
        now = self.clock()
        with sqlite3.connect(self.cache_path) as db:
            row = db.execute("SELECT body, fetched FROM cache WHERE key = ?", (key,)).fetchone()
        if row and 0 <= now - row[1] < min(ttl, max_age):
            return self.payload(row[0], row[1], True)
        for attempt in range(attempts):
            budget.acquire(self.clock, self.sleep)
            try:
                response = self.sender(url, headers, timeout)
            except DataError as exc:
                if exc.code not in ("timeout", "network") or attempt == attempts - 1:
                    raise
                self.sleep(2**attempt)
                continue
            status = response.status
            LOG.info("provider=%s status=%d attempt=%d", provider, status, attempt + 1)
            if status == 200:
                fetched = self.clock()
                require(len(response.body) <= MAX_BYTES, "Response exceeds size limit")
                with sqlite3.connect(self.cache_path) as db:
                    db.execute(
                        "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                        (key, response.body, fetched),
                    )
                return self.payload(response.body, fetched, False)
            codes = {401: "unauthorized", 403: "forbidden", 404: "missing", 429: "rate_limited"}
            if status == 429:
                shared_delay = self.retry_delay(response.headers.get("retry-after"), attempt)
                budget.defer(self.clock() + shared_delay)
            if status not in (429, 500, 502, 503, 504) or attempt == attempts - 1:
                raise DataError(
                    codes.get(status, "server" if status >= 500 else "http"),
                    "Provider request failed; response details redacted",
                    status=status,
                )
            delay = self.retry_delay(response.headers.get("retry-after"), attempt)
            if delay > 60:
                raise DataError(
                    "rate_limited", "Retry-After exceeds bounded request wait", status=status
                )
            budget.defer(self.clock() + delay)
            self.sleep(delay)
        raise DataError("network", "Retry budget exhausted")

    def retry_delay(self, value: str | None, attempt: int) -> float:
        if value is not None:
            try:
                delay = float(value)
            except ValueError:
                try:
                    delay = parsedate_to_datetime(value).timestamp() - self.clock()
                except (ValueError, TypeError, OverflowError):
                    delay = 2**attempt
            return max(0.0, delay) if math.isfinite(delay) else 61.0
        return float(2**attempt)

    @staticmethod
    def payload(body: bytes, fetched: float, cached: bool) -> Payload:
        return Payload(
            body,
            datetime.fromtimestamp(fetched, UTC).isoformat(),
            "sha256:" + hashlib.sha256(body).hexdigest(),
            cached,
        )
