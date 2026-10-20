import sqlite3
from pathlib import Path

import pytest

from lilly.domain.research import (
    JobListing,
    ResearchStrategy,
    deduplicate_listings,
    filter_active_listings,
    format_listings_csv,
    format_listings_markdown,
    normalize_url,
)
from lilly.domain.schedule import Schedule
from lilly.domain.tasks import ExecutionTarget
from lilly.store import playbooks, routines
from lilly.store.connection import open_db

# ==============================================================================
# Research & Job Listings Fixtures & Tests
# ==============================================================================

MOCK_JOB_BOARD_FIXTURE = [
    # Active normal listing
    JobListing(
        title="Senior Software Engineer",
        company="Acme Corp",
        location="Remote (US)",
        canonical_url="https://acme.example.com/jobs/101?utm_source=linkedin&ref=share",
        posted_date="2026-10-15",
        requisition_id="REQ-101",
        experience_level="Senior",
        salary="$160,000 - $190,000",
        source="Acme Careers",
        status="active",
    ),
    # Duplicate of REQ-101 with tracking params stripped
    JobListing(
        title="Senior Software Engineer",
        company="Acme Corp",
        location="Remote (US)",
        canonical_url="https://acme.example.com/jobs/101",
        posted_date="2026-10-15",
        requisition_id="REQ-101",
        experience_level="Senior",
        salary="$160,000 - $190,000",
        source="Aggregator Board",
        status="active",
    ),
    # Same company repost of the same title without req ID
    JobListing(
        title="Senior Software Engineer",
        company="Acme Corp",
        location="San Francisco, CA",
        canonical_url="https://acme.example.com/jobs/102",
        posted_date="2026-10-16",
        requisition_id=None,
        experience_level="Senior",
        salary="not stated",
        source="Acme Careers",
        status="active",
    ),
    # Missing date and missing salary
    JobListing(
        title="Staff Backend Engineer",
        company="Beta Labs",
        location="New York, NY",
        canonical_url="https://betalabs.example.com/careers/backend-staff",
        posted_date="not stated",
        requisition_id="BETA-88",
        experience_level="Staff",
        salary="not stated",
        source="Beta Labs",
        status="active",
    ),
    # Expired listing
    JobListing(
        title="Junior Frontend Engineer",
        company="Gamma Inc",
        location="Austin, TX",
        canonical_url="https://gamma.example.com/jobs/expired-99",
        posted_date="2026-08-01",
        requisition_id="GAMMA-99",
        experience_level="Entry",
        salary="$80,000",
        source="Gamma Careers",
        status="expired",
    ),
    # Blocked listing (e.g. login wall / CAPTCHA)
    JobListing(
        title="Data Engineer",
        company="Delta Co",
        location="Remote",
        canonical_url="https://delta.example.com/auth/login?next=/jobs/404",
        posted_date="not stated",
        requisition_id=None,
        experience_level="Mid",
        salary="not stated",
        source="Protected Portal",
        status="blocked",
    ),
]


def test_research_strategy_enum() -> None:
    assert ResearchStrategy.PUBLIC_WEB.value == "public_web"
    assert ResearchStrategy.VISIBLE_BROWSER.value == "visible_browser"
    assert ResearchStrategy.BOTH.value == "both"


def test_normalize_url_strips_tracking() -> None:
    raw = "https://example.com/jobs/123?utm_source=twitter&utm_medium=cpc&ref=xyz"
    assert normalize_url(raw) == "https://example.com/jobs/123"


def test_job_listing_deduplication() -> None:
    unique = deduplicate_listings(MOCK_JOB_BOARD_FIXTURE)
    # The fixture has:
    # 1. Acme Corp / Senior SWE (REQ-101)
    # 2. Duplicate of REQ-101 -> dropped
    # 3. Same company (Acme) / same title (Senior Software Engineer) -> dropped
    # 4. Beta Labs / Staff Backend Engineer -> kept
    # 5. Gamma Inc / Junior Frontend Engineer -> kept
    # 6. Delta Co / Data Engineer -> kept
    assert len(unique) == 4
    companies = [j.company for j in unique]
    assert companies == ["Acme Corp", "Beta Labs", "Gamma Inc", "Delta Co"]


def test_filter_active_listings() -> None:
    unique = deduplicate_listings(MOCK_JOB_BOARD_FIXTURE)
    active = filter_active_listings(unique)
    assert len(active) == 2
    assert all(j.status == "active" for j in active)
    assert {j.company for j in active} == {"Acme Corp", "Beta Labs"}


def test_format_listings_markdown() -> None:
    active = filter_active_listings(deduplicate_listings(MOCK_JOB_BOARD_FIXTURE))
    md = format_listings_markdown(active)
    assert "| Role | Company | Location | Posted | Salary | Source / Link |" in md
    assert "Senior Software Engineer" in md
    assert "[Acme Careers](https://acme.example.com/jobs/101" in md
    assert "Staff Backend Engineer" in md
    assert "not stated" in md


def test_format_listings_csv() -> None:
    active = filter_active_listings(deduplicate_listings(MOCK_JOB_BOARD_FIXTURE))
    csv_text = format_listings_csv(active)
    assert "title,company,location,posted_date,salary" in csv_text
    assert "Acme Corp" in csv_text
    assert "Beta Labs" in csv_text


# ==============================================================================
# Playbooks and Routines Persistence Tests
# ==============================================================================


@pytest.fixture
def memory_db(tmp_path: Path) -> sqlite3.Connection:
    return open_db(tmp_path / "test.db")


def test_playbooks_crud(memory_db: sqlite3.Connection) -> None:
    p = playbooks.create_playbook(
        memory_db,
        id="pb-1",
        name="Daily SWE Job Search",
        task_signature="search swe jobs",
        description="Search and summarize SWE job openings",
        steps=[{"tool": "web.search", "args": {"query": "SWE roles"}}],
        parameters={"query": "SWE roles"},
        target=ExecutionTarget.HOST,
        now=1000.0,
    )
    assert p.id == "pb-1"
    assert p.name == "Daily SWE Job Search"
    assert p.task_signature == "search swe jobs"
    assert p.description == "Search and summarize SWE job openings"
    assert p.target == ExecutionTarget.HOST
    assert p.version == 1
    assert p.success_count == 1
    assert len(p.steps) == 1

    fetched = playbooks.get_playbook(memory_db, "pb-1")
    assert fetched is not None
    assert fetched.parameters["query"] == "SWE roles"

    by_sig = playbooks.find_by_signature(memory_db, "search swe jobs")
    assert len(by_sig) == 1
    assert by_sig[0].id == "pb-1"

    updated = playbooks.increment_success(memory_db, "pb-1", 1050.0)
    assert updated.success_count == 2
    assert updated.updated_at == 1050.0

    playbooks.delete_playbook(memory_db, "pb-1")
    assert playbooks.get_playbook(memory_db, "pb-1") is None


def test_routine_with_target_and_playbook(memory_db: sqlite3.Connection) -> None:
    sched = Schedule(kind="every", every_minutes=60)
    r = routines.create_routine(
        memory_db,
        id="rt-1",
        name="Hourly DevBox Check",
        goal="Run tests in devbox",
        agent_id=None,
        schedule=sched,
        now=100.0,
        playbook_id="pb-dev",
        playbook_version=2,
        target=ExecutionTarget.DEVBOX,
    )
    assert r.id == "rt-1"
    assert r.target == ExecutionTarget.DEVBOX
    assert r.playbook_id == "pb-dev"
    assert r.playbook_version == 2

    # Update routine target
    updated = routines.update_routine(
        memory_db,
        "rt-1",
        150.0,
        target=ExecutionTarget.HOST,
    )
    assert updated.target == ExecutionTarget.HOST
    assert updated.playbook_id == "pb-dev"
