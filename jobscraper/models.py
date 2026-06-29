"""Shared data types."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Job:
    company: str
    job_id: str          # stable id from the source
    title: str
    url: str
    location: str = ""
    posted_at: str = ""  # free-form, whatever the source gives us
    source: str = ""     # "" for direct API, "simplify" for the aggregator

    @property
    def uid(self) -> str:
        """Globally unique, stable key used for dedup."""
        prefix = f"{self.source}:" if self.source else ""
        return f"{prefix}{self.company.lower()}::{self.job_id}"


@dataclass
class CompanyConfig:
    name: str
    adapter: str
    params: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
