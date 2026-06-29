"""Adapter registry: maps an adapter name to a fetch(company) -> list[Job] function."""
from __future__ import annotations

from collections.abc import Callable

from ..models import CompanyConfig, Job
from . import ats, ashby, amazon, microsoft, apple, google, meta

FetchFn = Callable[[CompanyConfig], list[Job]]

REGISTRY: dict[str, FetchFn] = {
    "greenhouse": ats.fetch_greenhouse,
    "lever": ats.fetch_lever,
    "workday": ats.fetch_workday,
    "eightfold": ats.fetch_eightfold,
    "ashby": ashby.fetch,
    "amazon": amazon.fetch,
    "microsoft": microsoft.fetch,
    "apple": apple.fetch,
    "google": google.fetch,
    "meta": meta.fetch,
}


def get(name: str) -> FetchFn | None:
    return REGISTRY.get(name)
