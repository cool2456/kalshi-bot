"""Rate-limited, cached client for Kalshi's public market-data API.

No authentication is used or needed. The client identifies itself honestly in the
User-Agent and paces itself to a rate measured as safe on 2026-08-21:

    4 req/s -> 60/60 HTTP 200
    8 req/s -> 41/60 HTTP 200, 19 HTTP 429

This is a free public endpoint. REQUESTS_PER_SECOND is a courtesy limit, not a
performance knob.

Responses are cached in a SQLite file keyed by URL so a long backfill is resumable and
so re-running the analysis costs no requests at all.
"""

from __future__ import annotations

import gzip
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

from .config import BASE_URL, CACHE_DIR, REQUESTS_PER_SECOND, USER_AGENT


class KalshiAPIUnreachable(RuntimeError):
    """Raised when the API cannot be reached.

    BUILD_PROMPT step 1: 'If the API is unreachable, stop and report it. Do not
    substitute a scraped aggregator or a third-party mirror.' Nothing in this package
    catches this and falls back to another data source.
    """


@dataclass
class RequestStats:
    sent: int = 0
    cache_hits: int = 0
    http_200: int = 0
    http_429: int = 0
    http_404: int = 0
    http_other: dict[int, int] = field(default_factory=dict)
    retries: int = 0
    total_wait_s: float = 0.0

    def summary(self) -> str:
        return (
            f"requests sent={self.sent} cache_hits={self.cache_hits} "
            f"200={self.http_200} 404={self.http_404} 429={self.http_429} "
            f"other={self.http_other} retries={self.retries} "
            f"throttle_wait={self.total_wait_s:.0f}s"
        )


def free_disk_gb(path: str = ".") -> float:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / (1024 ** 3)


class DiskSpaceExhausted(RuntimeError):
    """Raised when the response cache would push free disk below the guard threshold."""


class _RateLimiter:
    """Simple token-free pacer: never issue two requests closer than 1/rate apart."""

    def __init__(self, rate_per_second: float) -> None:
        self._gap = 1.0 / rate_per_second
        self._lock = threading.Lock()
        self._next_at = 0.0

    def acquire(self) -> float:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self._gap
        if wait > 0:
            time.sleep(wait)
        return wait


class KalshiClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        cache_path: str | None = None,
        rate_per_second: float = REQUESTS_PER_SECOND,
        offline: bool = False,
        min_free_gb: float = 2.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.offline = offline
        self.min_free_gb = min_free_gb
        self._disk_checked = 0
        self.stats = RequestStats()
        self._limiter = _RateLimiter(rate_per_second)
        os.makedirs(CACHE_DIR, exist_ok=True)
        self._cache_path = cache_path or os.path.join(CACHE_DIR, "http_cache.sqlite")
        self._local = threading.local()
        self._init_db()

    # ---------------- cache ----------------

    def _conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._cache_path, timeout=60)
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = c
        return c

    def _init_db(self) -> None:
        c = self._conn()
        c.execute(
            "CREATE TABLE IF NOT EXISTS resp ("
            "url TEXT PRIMARY KEY, status INTEGER, body BLOB, fetched_at REAL)"
        )
        c.commit()

    def cache_get(self, url: str) -> tuple[int, Any] | None:
        row = self._conn().execute(
            "SELECT status, body FROM resp WHERE url=?", (url,)
        ).fetchone()
        if row is None:
            return None
        status, blob = row
        if blob is None:
            return status, None
        return status, json.loads(gzip.decompress(blob).decode("utf8"))

    def _check_disk(self) -> None:
        """Stop rather than fill the user's disk. Checked every 500 cache writes."""
        self._disk_checked += 1
        if self._disk_checked % 500:
            return
        free = free_disk_gb(os.path.dirname(os.path.abspath(self._cache_path)) or ".")
        if free < self.min_free_gb:
            raise DiskSpaceExhausted(
                f"only {free:.2f} GB free, below the {self.min_free_gb} GB guard. "
                f"Stopping before filling the disk. Cached responses so far are kept, "
                f"so the run can resume after freeing space."
            )

    def cache_put(self, url: str, status: int, payload: Any) -> None:
        self._check_disk()
        blob = None if payload is None else gzip.compress(
            json.dumps(payload, separators=(",", ":")).encode("utf8")
        )
        c = self._conn()
        c.execute(
            "INSERT OR REPLACE INTO resp(url,status,body,fetched_at) VALUES (?,?,?,?)",
            (url, status, blob, time.time()),
        )
        c.commit()

    def cache_size(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM resp").fetchone()[0]

    def purge_cached(self, like_patterns: list[str]) -> int:
        """Drop cached responses matching SQL LIKE patterns and reclaim the file space.

        The census listing pages are large and are read exactly twice (pass 1 and pass 2).
        Once the sample is fixed they are dead weight, and on a machine that is short of
        disk they compete with the candlestick responses that the analysis actually needs.
        Purging them costs re-fetch time on a future run but not correctness.
        """
        c = self._conn()
        removed = 0
        for pat in like_patterns:
            cur = c.execute("DELETE FROM resp WHERE url LIKE ?", (pat,))
            removed += cur.rowcount or 0
        c.commit()
        c.execute("VACUUM")
        c.commit()
        return removed

    # ---------------- fetch ----------------

    def get(
        self,
        path: str,
        *,
        allow_404: bool = False,
        max_retries: int = 6,
        use_cache: bool = True,
    ) -> Any:
        """GET a path relative to the base URL, returning parsed JSON.

        404 returns None when allow_404 is set, and the 404 itself is cached so a
        resumed run does not re-request known-missing resources.
        """
        url = self.base_url + path
        if use_cache:
            hit = self.cache_get(url)
            if hit is not None:
                status, payload = hit
                self.stats.cache_hits += 1
                if status == 404:
                    if allow_404:
                        return None
                    raise KalshiAPIUnreachable(f"cached 404 for {url}")
                return payload

        if self.offline:
            raise KalshiAPIUnreachable(
                f"offline mode and no cached response for {url}. "
                "Run the ingest step first."
            )

        backoff = 1.0
        last_err: str = ""
        for attempt in range(max_retries):
            self.stats.total_wait_s += self._limiter.acquire()
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            try:
                self.stats.sent += 1
                with urllib.request.urlopen(req, timeout=60) as r:
                    payload = json.load(r)
                self.stats.http_200 += 1
                self.cache_put(url, 200, payload)
                return payload
            except urllib.error.HTTPError as e:
                code = e.code
                body = ""
                try:
                    body = e.read()[:300].decode("utf8", "replace")
                except Exception:
                    pass
                last_err = f"HTTP {code} {body}"
                if code == 404:
                    self.stats.http_404 += 1
                    self.cache_put(url, 404, None)
                    if allow_404:
                        return None
                    raise KalshiAPIUnreachable(f"404 for {url}") from e
                if code == 429:
                    self.stats.http_429 += 1
                elif code >= 400:
                    self.stats.http_other[code] = self.stats.http_other.get(code, 0) + 1
                    if code < 500 and code != 429:
                        # a genuine client error: retrying will not help
                        raise KalshiAPIUnreachable(f"{last_err} for {url}") from e
            except Exception as e:  # network / timeout / json
                last_err = f"{type(e).__name__}: {e}"

            self.stats.retries += 1
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)

        raise KalshiAPIUnreachable(
            f"gave up after {max_retries} attempts on {url}: {last_err}"
        )

    # ---------------- paging ----------------

    def paginate(
        self, path: str, key: str, *, limit: int = 1000, max_pages: int | None = None
    ) -> Iterator[list[dict]]:
        """Yield successive pages of a cursor-paginated list endpoint.

        The cursor is part of the cache key, so a resumed run replays the same page
        sequence from cache without re-requesting it.
        """
        sep = "&" if "?" in path else "?"
        cursor: str | None = None
        pages = 0
        while True:
            p = f"{path}{sep}limit={limit}" + (f"&cursor={cursor}" if cursor else "")
            payload = self.get(p)
            items = payload.get(key) or []
            yield items
            pages += 1
            cursor = payload.get("cursor") or None
            if not cursor or not items:
                return
            if max_pages is not None and pages >= max_pages:
                return


def check_reachable(client: KalshiClient) -> dict:
    """BUILD step 1 precondition. Raises KalshiAPIUnreachable rather than falling back."""
    return client.get("/exchange/status", use_cache=False)
