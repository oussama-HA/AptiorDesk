"""Local ingestion endpoint for the AptiorDesk browser extension.

The extension is intentionally user-driven: it reads only the active job page
and only after the user presses its capture button. It does not crawl,
search, click, or automate any job board.

The bridge binds to loopback, accepts job pages from any HTTP(S) website,
automatically pairs extension origins with a per-process token, caps request
size, and stores through ``JobService``.  The token exists only in memory and
changes every time AptiorDesk starts; there is nothing for the user to copy.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

from aptiordesk.core.identity import BROWSER_TOKEN_HEADER, LEGACY_BROWSER_TOKEN_HEADER
from aptiordesk.database.db import connect
from aptiordesk.database.models.job import EmploymentType, ExperienceLevel, JobPosting, RemoteType
from aptiordesk.features.jobs.service import JobService
from aptiordesk.integrations.browser_extension.config import (
    ALLOWED_EXTENSION_ORIGINS,
    BRIDGE_HOST,
    BRIDGE_PORT,
)

log = logging.getLogger(__name__)

DEFAULT_HOST = BRIDGE_HOST
DEFAULT_PORT = BRIDGE_PORT
TOKEN_SETTING = "browser_extension.token"
MAX_REQUEST_BYTES = 256 * 1024


class BrowserJobPayload(BaseModel):
    """Untrusted JSON sent by the extension after it extracts visible text."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    url: str = Field(min_length=8, max_length=4096)
    title: str = Field(min_length=1, max_length=500)
    company: str = Field(default="", max_length=500)
    location: str = Field(default="", max_length=500)
    description: str = Field(min_length=20, max_length=200_000)
    posted_at: str = Field(default="", max_length=64)
    remote_type: str = Field(default="unknown", max_length=32)
    employment_type: str = Field(default="unknown", max_length=32)
    experience_level: str = Field(default="unknown", max_length=32)
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = Field(default="", max_length=8)
    salary_period: str = Field(default="", max_length=16)
    skills: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("skills")
    @classmethod
    def _clean_skills(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            skill = " ".join(str(value).split())[:100]
            key = skill.casefold()
            if skill and key not in seen:
                seen.add(key)
                result.append(skill)
        return result


def supported_source(url: str) -> tuple[str, str]:
    """Return a stable source id/name for any browser-accessible website."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only HTTP or HTTPS job listing URLs are accepted.")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise ValueError("The job page URL does not contain a valid website host.")
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        return "linkedin", "LinkedIn"
    indeed_domains = (
        "indeed.com",
        "indeed.co.uk",
        "indeed.ca",
        "indeed.de",
        "indeed.fr",
        "indeed.com.au",
        "indeed.nl",
        "indeed.ie",
        "indeed.co.in",
    )
    if any(host == domain or host.endswith("." + domain) for domain in indeed_domains):
        return "indeed", "Indeed"
    glassdoor_domains = (
        "glassdoor.com",
        "glassdoor.co.uk",
        "glassdoor.ca",
        "glassdoor.de",
        "glassdoor.fr",
        "glassdoor.com.au",
    )
    if any(host == domain or host.endswith("." + domain) for domain in glassdoor_domains):
        return "glassdoor", "Glassdoor"
    return f"web:{host}"[:200], _website_name(host)


def _website_name(host: str) -> str:
    """Produce a useful attribution label without pretending to know the brand."""
    labels = [part for part in host.split(".") if part not in {"www", "jobs", "careers"}]
    stem = labels[-2] if len(labels) >= 2 else labels[0]
    return stem.replace("-", " ").replace("_", " ").title() or host


def canonical_listing(url: str, source: str) -> tuple[str, str]:
    """Return a stable listing id and a URL stripped of tracking parameters."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    source_id = ""
    clean_query: dict[str, str] = {}
    if source == "linkedin":
        match = re.search(r"/jobs/(?:collections/[^/]+/|view/)(\d+)", parsed.path)
        source_id = match.group(1) if match else (query.get("currentJobId") or [""])[0]
        if source_id:
            parsed = parsed._replace(path=f"/jobs/view/{source_id}/")
    elif source == "indeed":
        source_id = (query.get("jk") or query.get("vjk") or [""])[0]
        if source_id:
            clean_query["jk"] = source_id
    elif source == "glassdoor":
        source_id = (
            query.get("jobListingId") or query.get("jl") or query.get("jobListingID") or [""]
        )[0]
        if source_id:
            clean_query["jl"] = source_id
    else:
        # Preserve unknown query parameters because they may contain the
        # listing identity. Remove only well-known marketing/tracking keys.
        tracking = {
            "fbclid",
            "gclid",
            "mc_cid",
            "mc_eid",
            "ref",
            "refid",
            "trk",
            "trackingid",
            "campaign",
            "campaignid",
        }
        clean_query = {
            key: value
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in tracking
        }

    cleaned = urlunparse(parsed._replace(query=urlencode(clean_query), fragment=""))
    if not source_id:
        source_id = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:32]
    return source_id[:200], cleaned


def import_browser_job(conn, payload: BrowserJobPayload) -> tuple[int, bool]:
    source, source_name = supported_source(payload.url)
    source_id, url = canonical_listing(payload.url, source)
    posting = JobPosting(
        source=source,
        source_name=source_name,
        source_id=source_id,
        url=url,
        title=payload.title,
        company=payload.company,
        location=payload.location,
        description=payload.description,
        posted_at=payload.posted_at,
        retrieved_at=datetime.now(UTC).isoformat(),
        remote_type=_enum_value(RemoteType, payload.remote_type),
        employment_type=_enum_value(EmploymentType, payload.employment_type),
        experience_level=_enum_value(ExperienceLevel, payload.experience_level),
        salary_min=payload.salary_min,
        salary_max=payload.salary_max,
        salary_currency=payload.salary_currency,
        salary_period=payload.salary_period,
        skills=payload.skills,
    )
    job, existed = JobService(conn).import_posting(posting)
    return int(job.id), existed


def _enum_value(enum_type, value: str):
    try:
        return enum_type((value or "unknown").lower())
    except ValueError:
        return enum_type("unknown")


class _ImportHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    db_path: Path
    on_import: Callable[[int], None] | None
    pairing_token: str


class _Handler(BaseHTTPRequestHandler):
    server: _ImportHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args) -> None:
        log.debug("Browser extension bridge: " + format, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._origin_allowed():
            self._json(403, {"ok": False, "error": "Origin not allowed."})
            return
        self.send_response(204)
        self._cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            f"Content-Type, {BROWSER_TOKEN_HEADER}, {LEGACY_BROWSER_TOKEN_HEADER}",
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/status":
            self._json(
                200,
                {
                    "ok": True,
                    "service": "AptiorDesk browser import",
                    "version": 2,
                    "pairing": "automatic",
                },
            )
            return
        if self.path == "/v1/pair":
            if not self._origin_allowed():
                self._json(403, {"ok": False, "error": "Origin not allowed."})
                return
            try:
                # Imported lazily to keep the bridge independent during module
                # initialization and to avoid persisting the temporary token.
                from aptiordesk.core.system_health import mark_extension_paired

                mark_extension_paired()
            except OSError:
                log.warning("Could not record browser-extension pairing", exc_info=True)
            self._json(
                200,
                {
                    "ok": True,
                    "token": self.server.pairing_token,
                    "expires": "when AptiorDesk closes",
                },
            )
            return
        self._json(404, {"ok": False, "error": "Not found."})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/jobs/import":
            self._json(404, {"ok": False, "error": "Not found."})
            return
        if not self._origin_allowed():
            self._json(403, {"ok": False, "error": "Origin not allowed."})
            return
        if not self._authorised():
            self._json(401, {"ok": False, "error": "Pairing key is missing or incorrect."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"ok": False, "error": "Request is empty or too large."})
            return
        try:
            raw = json.loads(self.rfile.read(length))
            payload = BrowserJobPayload.model_validate(raw)
            conn = connect(self.server.db_path)
            try:
                job_id, existed = import_browser_job(conn, payload)
            finally:
                conn.close()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(422, {"ok": False, "error": str(exc)[:500]})
            return
        except Exception:
            log.exception("Browser job import failed")
            self._json(500, {"ok": False, "error": "AptiorDesk could not save this job."})
            return
        if self.server.on_import:
            self.server.on_import(job_id)
        self._json(
            200,
            {
                "ok": True,
                "job_id": job_id,
                "already_saved": existed,
                "message": "Job updated." if existed else "Job saved to AptiorDesk.",
            },
        )

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        return origin in ALLOWED_EXTENSION_ORIGINS

    def _authorised(self) -> bool:
        supplied = self.headers.get(BROWSER_TOKEN_HEADER, "") or self.headers.get(
            LEGACY_BROWSER_TOKEN_HEADER, ""
        )
        return bool(supplied) and hmac.compare_digest(supplied, self.server.pairing_token)

    def _cors_headers(self) -> None:
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_EXTENSION_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class BrowserImportServer:
    """Lifecycle wrapper used by the desktop app and integration tests."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        on_import: Callable[[int], None] | None = None,
    ):
        self.db_path = Path(db_path)
        self.host = host
        self.port = port
        self.on_import = on_import
        self._httpd: _ImportHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> bool:
        if self._httpd is not None:
            return True
        try:
            httpd = _ImportHTTPServer((self.host, self.port), _Handler)
        except OSError as exc:
            log.warning("Browser extension bridge could not start: %s", exc)
            return False
        httpd.db_path = self.db_path
        httpd.on_import = self.on_import
        httpd.pairing_token = secrets.token_urlsafe(32)
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        self._thread = threading.Thread(
            target=httpd.serve_forever,
            name="aptiordesk-browser-import",
            daemon=True,
        )
        self._thread.start()
        log.info("Browser extension bridge listening on %s", self.base_url)
        return True

    def stop(self) -> None:
        httpd, self._httpd = self._httpd, None
        if httpd is None:
            return
        httpd.shutdown()
        httpd.server_close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
        self._thread = None


__all__ = [
    "BrowserImportServer",
    "BrowserJobPayload",
    "DEFAULT_PORT",
    "TOKEN_SETTING",
    "canonical_listing",
    "import_browser_job",
    "supported_source",
]
