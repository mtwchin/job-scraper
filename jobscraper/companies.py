"""Parse companies.md (a markdown table) into CompanyConfig objects."""
from __future__ import annotations

from pathlib import Path

from .models import CompanyConfig


def _parse_params(raw: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in raw.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        params[key.strip()] = value.strip()
    return params


def _split_row(line: str) -> list[str]:
    # "| a | b | c |" -> ["a", "b", "c"]
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def load_companies(path: Path) -> list[CompanyConfig]:
    """Read every markdown table row that looks like a company definition.

    Expected columns (header names are matched case-insensitively):
        Company | Adapter | Config | On | Notes
    Rows whose first cell is empty, a separator (---), or the header are skipped.
    """
    text = path.read_text(encoding="utf-8")
    header: list[str] | None = None
    companies: list[CompanyConfig] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = _split_row(stripped)
        # Separator row like |---|---|
        if all(set(c) <= {"-", ":"} and c for c in cells):
            continue
        lowered = [c.lower() for c in cells]
        if header is None:
            if "company" in lowered and "adapter" in lowered:
                header = lowered
            continue

        row = dict(zip(header, cells))
        name = row.get("company", "").strip()
        adapter = row.get("adapter", "").strip().lower()
        if not name or not adapter:
            continue

        on = row.get("on", "yes").strip().lower()
        enabled = on in {"yes", "y", "true", "1", "on"}
        params = _parse_params(row.get("config", ""))

        companies.append(
            CompanyConfig(name=name, adapter=adapter, params=params, enabled=enabled)
        )

    return companies
