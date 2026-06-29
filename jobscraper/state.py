"""Persist which jobs we've already seen so we only notify on new ones."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self._seen: dict[str, dict] = {}
        self.existed = path.exists()
        if self.existed:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._seen = data.get("jobs", {})
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

    def save(self) -> None:
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "count": len(self._seen),
            "jobs": self._seen,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._seen)
