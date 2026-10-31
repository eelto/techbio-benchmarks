"""Polite HTTP fetcher with a content-addressed raw cache.

Raw documents land in the gitignored data/raw/ directory, named by sha256. They never leave this
machine: exports carry structured facts and links only.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import httpx

from techbio import __version__
from techbio.core.config import load_yaml, secret, settings
from techbio.core.ids import sha256_bytes, sha256_text

GENERIC_UA = f"techbio-benchmarks/{__version__} (research; github.com/techbio-benchmarks)"
SEC_HOSTS = ("sec.gov", "www.sec.gov", "data.sec.gov", "efts.sec.gov")


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    content: bytes
    sha256: str
    local_path: Path
    content_type: str
    retrieved_at: datetime
    from_cache: bool

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        return json.loads(self.content)


class _RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str, per_second: float) -> None:
        with self._lock:
            now = time.monotonic()
            t = max(self._next.get(host, now), now)
            self._next[host] = t + 1.0 / per_second
        delay = t - now
        if delay > 0:
            time.sleep(delay)


_limiter = _RateLimiter()


def _host_rate(host: str) -> float:
    src = load_yaml("sources")
    if host.endswith("sec.gov"):
        return float(src["sec"]["max_requests_per_second"])
    if host.endswith("clinicaltrials.gov"):
        return float(src["ctgov"]["max_requests_per_second"])
    if host.endswith("federalregister.gov"):
        return float(src["fedreg"]["max_requests_per_second"])
    return 2.0


def _user_agent(host: str) -> str:
    if host in SEC_HOSTS or host.endswith(".sec.gov"):
        ua = secret(load_yaml("sources")["sec"]["user_agent_env"])
        if "@" not in ua:
            raise RuntimeError(
                "SEC_USER_AGENT must include a contact email (SEC fair-access policy)"
            )
        return ua
    return GENERIC_UA


class Fetcher:
    def __init__(self, raw_dir: Path | None = None, timeout: float = 60.0) -> None:
        self.raw_dir = raw_dir or settings().raw_dir
        self.index_dir = self.raw_dir / "_index"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.Client(timeout=timeout, follow_redirects=True, http2=False)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _index_path(self, url: str) -> Path:
        return self.index_dir / f"{sha256_text(url)}.json"

    def _store(self, content: bytes, content_type: str) -> tuple[str, Path]:
        digest = sha256_bytes(content)
        ext = (
            ".json"
            if "json" in content_type
            else ".zip"
            if "zip" in content_type
            else ".xml"
            if "xml" in content_type
            else ".html"
            if "html" in content_type
            else ".txt"
        )
        path = self.raw_dir / digest[:2] / f"{digest}{ext}"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return digest, path

    def get(
        self,
        url: str,
        params: dict | None = None,
        max_age: timedelta | None = None,
        retries: int = 4,
    ) -> FetchResult:
        """GET with rate limiting and retries. If `max_age` is set and a cached copy of this exact
        URL is younger than that, return it without a request."""
        full_url = str(httpx.URL(url, params=params)) if params else url
        idx = self._index_path(full_url)
        if max_age is not None and idx.exists():
            meta = json.loads(idx.read_text())
            fetched = datetime.fromisoformat(meta["retrieved_at"])
            path = Path(meta["local_path"])
            if datetime.now(UTC) - fetched < max_age and path.exists():
                return FetchResult(
                    url=full_url,
                    status=meta["status"],
                    content=path.read_bytes(),
                    sha256=meta["sha256"],
                    local_path=path,
                    content_type=meta["content_type"],
                    retrieved_at=fetched,
                    from_cache=True,
                )
        host = urlparse(full_url).hostname or ""
        headers = {"User-Agent": _user_agent(host), "Accept-Encoding": "gzip, deflate"}
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            _limiter.wait(host, _host_rate(host))
            try:
                r = self.client.get(full_url, headers=headers)
            except httpx.TransportError as e:
                last_exc = e
                time.sleep(2**attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                retry_after = r.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(wait, 60))
                last_exc = httpx.HTTPStatusError(
                    f"{r.status_code} for {full_url}", request=r.request, response=r
                )
                continue
            r.raise_for_status()
            ctype = r.headers.get("content-type", "application/octet-stream")
            digest, path = self._store(r.content, ctype)
            now = datetime.now(UTC).replace(microsecond=0)
            idx.write_text(
                json.dumps(
                    {
                        "url": full_url,
                        "status": r.status_code,
                        "sha256": digest,
                        "local_path": str(path),
                        "content_type": ctype,
                        "retrieved_at": now.isoformat(),
                    }
                )
            )
            return FetchResult(
                url=full_url,
                status=r.status_code,
                content=r.content,
                sha256=digest,
                local_path=path,
                content_type=ctype,
                retrieved_at=now,
                from_cache=False,
            )
        raise RuntimeError(f"GET failed after {retries + 1} attempts: {full_url}") from last_exc
