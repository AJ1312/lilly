"""Research domain: research strategy, structured job listings, and deduplication/ranking."""
from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any


class ResearchStrategy(str, Enum):
    PUBLIC_WEB = "public_web"
    VISIBLE_BROWSER = "visible_browser"
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class JobListing:
    title: str
    company: str
    location: str
    canonical_url: str
    posted_date: str = "not stated"
    requisition_id: str | None = None
    experience_level: str = "not stated"
    salary: str = "not stated"
    source: str = "unknown"
    verified_at: float | None = None
    status: str = "active"  # "active" | "expired" | "blocked"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_url(url: str) -> str:
    """Strip tracking query parameters for canonical deduplication."""
    clean = re.sub(r"[?&](utm_[^&=]+|ref|source|trackingId)=[^&=]*", "", url)
    clean = clean.rstrip("?&")
    return clean.strip().rstrip("/")


def deduplicate_listings(listings: list[JobListing]) -> list[JobListing]:
    """Deduplicate listings by canonical URL or (company, req_id) or (company, title)."""
    seen_urls: set[str] = set()
    seen_reqs: set[tuple[str, str]] = set()
    seen_roles: set[tuple[str, str]] = set()
    unique: list[JobListing] = []

    for item in listings:
        canon_url = normalize_url(item.canonical_url)
        company_key = item.company.strip().lower()
        title_key = item.title.strip().lower()

        if canon_url and canon_url in seen_urls:
            continue
        if item.requisition_id and (company_key, item.requisition_id) in seen_reqs:
            continue
        if (company_key, title_key) in seen_roles:
            continue

        if canon_url:
            seen_urls.add(canon_url)
        if item.requisition_id:
            seen_reqs.add((company_key, item.requisition_id))
        seen_roles.add((company_key, title_key))
        unique.append(item)

    return unique


def filter_active_listings(listings: list[JobListing]) -> list[JobListing]:
    """Filter out expired or blocked listings."""
    return [item for item in listings if item.status == "active"]


def format_listings_markdown(listings: list[JobListing]) -> str:
    """Format structured job listings into a Markdown table with exact links and citations."""
    if not listings:
        return "No job listings found matching the criteria."

    lines = [
        "| Role | Company | Location | Posted | Salary | Source / Link |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for job in listings:
        link_str = f"[{job.source}]({job.canonical_url})" if job.canonical_url else job.source
        lines.append(
            f"| {job.title} | {job.company} | {job.location} | {job.posted_date} | {job.salary} | {link_str} |"
        )
    return "\n".join(lines)


def format_listings_csv(listings: list[JobListing]) -> str:
    """Format listings as CSV text."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "title", "company", "location", "posted_date", "salary",
        "experience_level", "canonical_url", "source", "status", "verified_at"
    ])
    for job in listings:
        writer.writerow([
            job.title, job.company, job.location, job.posted_date, job.salary,
            job.experience_level, job.canonical_url, job.source, job.status, job.verified_at or ""
        ])
    return output.getvalue()
