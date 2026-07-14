"""Persist which jobs we've already seen so we only notify on new ones."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self._seen: dict[str, dict] = {}
        # Tracks whether the "all companies" Simplify feed has done its own quiet
        # first-run seed — separate from `existed`, since that feed can be turned
        # on long after the main store already exists (and shouldn't dump its
        # whole backlog the moment DISCORD_WEBHOOK_URL_ALL is set).
        self.simplify_all_seeded = False
        self.existed = path.exists()
        if self.existed:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._seen = data.get("jobs", {})
                self.simplify_all_seeded = bool(data.get("simplify_all_seeded", False))
            except (json.JSONDecodeError, OSError):
                self._seen = {}
                self.existed = False

    def is_new(self, uid: str) -> bool:
        return uid not in self._seen

    def add(self, uid: str, title: str, company: str, url: str, posted_at: str = "") -> None:
        self._seen[uid] = {
            "title": title,
            "company": company,
            "url": url,
            "posted_at": posted_at,  # the board's posting time, for freshness auditing
            "first_seen": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }

    def mark_simplify_all_seeded(self) -> None:
        self.simplify_all_seeded = True

    def save(self) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(self._seen),
            "simplify_all_seeded": self.simplify_all_seeded,
            "jobs": self._seen,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._seen)
