"""Universal browser ingestion, automatic pairing, and persistence."""

from __future__ import annotations

import threading

import httpx
import pytest

from aptiordesk.core.identity import LEGACY_BROWSER_TOKEN_HEADER
from aptiordesk.database import db
from aptiordesk.database.repositories.job_repo import JobRepository
from aptiordesk.integrations.browser_extension.bridge import (
    BrowserImportServer,
    BrowserJobPayload,
    canonical_listing,
    import_browser_job,
    supported_source,
)
from aptiordesk.integrations.browser_extension.config import (
    BRIDGE_BASE_URL,
    EXTENSION_ID,
    EXTENSION_ORIGIN,
)


def _payload(**overrides) -> dict:
    payload = {
        "url": "https://www.linkedin.com/jobs/view/123456789/?trk=tracking",
        "title": "Senior Data Engineer",
        "company": "Analytical Engines Ltd",
        "location": "London, UK",
        "description": "Build reliable Python and Airflow pipelines for production systems.",
        "posted_at": "2026-07-20",
        "remote_type": "hybrid",
        "employment_type": "full_time",
        "experience_level": "senior",
        "skills": ["Python", "Airflow", "Python"],
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("url", "source"),
    [
        ("https://www.linkedin.com/jobs/view/1", "linkedin"),
        ("https://uk.indeed.com/viewjob?jk=abc", "indeed"),
        ("https://www.glassdoor.co.uk/job-listing/x?jl=42", "glassdoor"),
    ],
)
def test_supported_job_board_urls_are_identified(url, source):
    assert supported_source(url)[0] == source


@pytest.mark.parametrize(
    ("url", "source", "name"),
    [
        ("https://jobs.example.com/openings/42", "web:jobs.example.com", "Example"),
        ("https://boards.greenhouse.io/acme/jobs/1", "web:boards.greenhouse.io", "Greenhouse"),
        (
            "http://careers.small-company.test/role/7",
            "web:careers.small-company.test",
            "Small Company",
        ),
    ],
)
def test_any_web_job_source_is_attributed(url, source, name):
    assert supported_source(url) == (source, name)


@pytest.mark.parametrize("url", ["file:///tmp/job.html", "chrome://extensions", "not-a-url"])
def test_non_web_urls_are_rejected(url):
    with pytest.raises(ValueError):
        supported_source(url)


def test_listing_identity_is_stable_and_tracking_is_removed():
    source_id, url = canonical_listing(
        "https://www.linkedin.com/jobs/view/123456789/?trk=feed&refId=secret",
        "linkedin",
    )

    assert source_id == "123456789"
    assert url == "https://www.linkedin.com/jobs/view/123456789/"

    panel_id, panel_url = canonical_listing(
        "https://www.linkedin.com/jobs/collections/recommended/?currentJobId=123456789&trk=feed",
        "linkedin",
    )
    assert panel_id == source_id
    assert panel_url == url

    generic_id, generic_url = canonical_listing(
        "https://careers.example.com/roles/42?department=data&utm_source=email&gclid=abc",
        "web:careers.example.com",
    )
    assert len(generic_id) == 32
    assert generic_url == "https://careers.example.com/roles/42?department=data"


def test_direct_import_uses_existing_job_deduplication(conn):
    payload = BrowserJobPayload.model_validate(_payload())

    first_id, existed = import_browser_job(conn, payload)
    second_id, existed_again = import_browser_job(
        conn,
        BrowserJobPayload.model_validate(
            _payload(description="An updated description with Python, SQL, and Airflow.")
        ),
    )

    assert not existed
    assert existed_again
    assert second_id == first_id
    jobs = JobRepository(conn).list()
    assert len(jobs) == 1
    assert jobs[0].source == "linkedin"
    assert "updated description" in jobs[0].raw_description
    assert jobs[0].skills == ["Python", "Airflow"]


def test_direct_import_accepts_a_company_careers_site(conn):
    payload = BrowserJobPayload.model_validate(
        _payload(
            url="https://careers.northstar.example/openings/product-engineer?utm_source=mail",
            title="Product Engineer",
            company="Northstar",
        )
    )

    job_id, existed = import_browser_job(conn, payload)

    assert not existed
    job = JobRepository(conn).get(job_id)
    assert job.source == "web:careers.northstar.example"
    assert job.source_name == "Northstar"
    assert job.url == "https://careers.northstar.example/openings/product-engineer"


def test_loopback_server_pairs_automatically_and_imports(tmp_path):
    database = tmp_path / "aptiordesk.db"
    conn = db.open_database(database)
    imported = threading.Event()
    server = BrowserImportServer(database, port=0, on_import=lambda _: imported.set())
    assert server.start()
    try:
        pairing = httpx.get(
            server.base_url + "/v1/pair",
            headers={"Origin": EXTENSION_ORIGIN},
            timeout=5,
        )
        assert pairing.status_code == 200
        token = pairing.json()["token"]
        assert len(token) >= 24

        response = httpx.post(
            server.base_url + "/v1/jobs/import",
            json=_payload(),
            headers={"Origin": EXTENSION_ORIGIN},
            timeout=5,
        )
        assert response.status_code == 401

        response = httpx.post(
            server.base_url + "/v1/jobs/import",
            json=_payload(),
            headers={
                "Origin": EXTENSION_ORIGIN,
                "X-AptiorDesk-Token": token,
            },
            timeout=5,
        )
        assert response.status_code == 200
        assert response.json()["ok"]
        assert imported.wait(1)
        assert len(JobRepository(conn).list()) == 1

        legacy_response = httpx.post(
            server.base_url + "/v1/jobs/import",
            json=_payload(),
            headers={
                "Origin": EXTENSION_ORIGIN,
                LEGACY_BROWSER_TOKEN_HEADER: token,
            },
            timeout=5,
        )
        assert legacy_response.status_code == 200
        assert legacy_response.json()["already_saved"] is True
    finally:
        server.stop()
        conn.close()


def test_loopback_server_rejects_web_page_origins(tmp_path):
    database = tmp_path / "aptiordesk.db"
    conn = db.open_database(database)
    server = BrowserImportServer(database, port=0)
    assert server.start()
    try:
        pairing = httpx.get(
            server.base_url + "/v1/pair",
            headers={"Origin": "https://evil.example"},
            timeout=5,
        )
        assert pairing.status_code == 403

        response = httpx.post(
            server.base_url + "/v1/jobs/import",
            json=_payload(),
            headers={"Origin": "https://evil.example", "X-AptiorDesk-Token": "not-valid"},
            timeout=5,
        )
        assert response.status_code == 403
        assert JobRepository(conn).list() == []
    finally:
        server.stop()
        conn.close()


def test_only_the_central_production_extension_origin_is_allowed(tmp_path):
    database = tmp_path / "aptiordesk.db"
    conn = db.open_database(database)
    server = BrowserImportServer(database, port=0)
    assert server.start()
    try:
        for origin in (
            "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            f"moz-extension://{EXTENSION_ID}",
        ):
            response = httpx.get(
                server.base_url + "/v1/pair",
                headers={"Origin": origin},
                timeout=5,
            )
            assert response.status_code == 403

        assert len(EXTENSION_ID) == 32
        assert EXTENSION_ORIGIN == f"chrome-extension://{EXTENSION_ID}"
        assert BRIDGE_BASE_URL == "http://127.0.0.1:8765"
    finally:
        server.stop()
        conn.close()


def test_desktop_uses_the_logo_derived_tokens():
    from aptiordesk.ui.theme.shared import TOKEN_FILE, token
    from aptiordesk.ui.theme.tokens import DARK

    css = TOKEN_FILE.read_text(encoding="utf-8")
    assert token("brand-coral") == "#FF5757"
    assert token("brand-black") == "#000000"
    assert token("brand-white") == "#FFFFFF"
    assert token("brand-gray") == "#727272"
    assert token("brand-pink") == "#E2A59F"
    assert token("brand-yellow") == "#F5C826"
    assert DARK.accent == token("brand-coral")
    assert "--ad-control-height" in css
