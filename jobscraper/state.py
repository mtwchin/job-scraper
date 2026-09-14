"""Persist which postings we've already alerted on, so we only notify once.

The store is the single source of truth for "has this been sent to Discord".
It indexes every recorded job three ways (see `dedup`) — per-source uid,
canonical apply URL, and company/title/location fingerprint — so a posting that
reaches us through two different sources is recognized as one job.

Writes are atomic (tmp file + replace). `save()` is cheap enough to call right
after each Discord batch, which matters: state that is only flushed at the end
of a run is state that gets lost when the run dies mid-way, and lost state means
re-notifying everything next time.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import dedup
from .models import Job

_SCHEMA = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class SeenStore:
    def __init__(self, path: Path):
        self.path = path
        self._seen: dict[str, dict] = {}
        self._by_url: dict[str, str] = {}
        self._by_fp: dict[str, str] = {}
        self._dirty = False
        # Tracks whether the "all companies" aggregate feed has done its own
        # quiet first-run seed — separate from `existed`, since that feed can be
        # switched on long after the main store exists and shouldn't dump its
        # whole backlog the moment its webhook is set.
        self.simplify_all_seeded = False
        # Sources whose existing backlog has already been absorbed. Adding a new
        # source must not dump its entire back catalogue into Discord as if it
        # had all just been posted, so an unrecognized source is seeded quietly
        # on first sight and only alerts on what appears afterwards.
        self.seeded_sources: set[str] = set()
        self.existed = path.exists()
        if self.existed:
            self._load()

    # -- loading ------------------------------------------------------------ #
    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt/unreadable store is treated as absent, but we must not
            # then "seed quietly" over a store that really did exist — that
            # would silently swallow a backlog we may never have sent. Callers
            # see existed=False and SEED_QUIETLY decides; the tmp+replace write
            # below makes a torn file very unlikely in the first place.
            self._seen = {}
            self.existed = False
            return
        self._seen = data.get("jobs", {}) or {}
        self.simplify_all_seeded = bool(data.get("simplify_all_seeded", False))
        stored = data.get("seeded_sources")
        # A store written before this field existed still represents sources we
        # have long been alerting on. Recover them from the records themselves
        # so upgrading doesn't look like "every source is brand new" and re-seed
        # (or worse, re-send) the whole back catalogue.
        self.seeded_sources = set(stored) if stored is not None else self._infer_sources()
        self._reindex()

    def _infer_sources(self) -> set[str]:
        """Which sources the stored records came from, for a pre-v2 store.

        `Job.uid` is "<source>:<company>::<job_id>", with the source prefix
        omitted entirely for a company's own ATS — so the text before the first
        ':' is the source, and its absence means the direct-adapter source ("").
        """
        sources = set()
        for uid, rec in self._seen.items():
            if "source" in rec:
                sources.add(rec.get("source", ""))
                continue
            head = uid.split("::", 1)[0]
            sources.add(head.split(":", 1)[0] if ":" in head else "")
        return sources

    def _reindex(self) -> None:
        """Rebuild the URL and fingerprint indexes from stored records.

        Runs on every load so state written by an older version (which recorded
        neither index) still dedups across sources — the 100+ double-posts that
        motivated this are all in that old data.
        """
        self._by_url.clear()
        self._by_fp.clear()
        for uid, rec in self._seen.items():
            if (key := dedup.canonical_url(rec.get("url", ""))):
                self._by_url.setdefault(key, uid)
            # Only index a fingerprint when the record carries a location.
            # Older records have none, and a locationless fingerprint is too
            # weak to suppress a posting on.
            if (loc := rec.get("location", "")):
                fp = dedup.fingerprint(rec.get("company", ""), rec.get("title", ""), loc)
                if fp:
                    self._by_fp.setdefault(fp, uid)

    # -- queries ------------------------------------------------------------ #
    def is_new(self, job: Job, *, use_fingerprint: bool = True) -> bool:
        """True if we have never alerted on this posting under any of its keys."""
        return self.match(job, use_fingerprint=use_fingerprint) is None

    def match(self, job: Job, *, use_fingerprint: bool = True) -> str | None:
        """Return which key matched an already-seen posting: 'uid', 'url', or
        'fingerprint'. None means the posting is genuinely new."""
        if job.uid in self._seen:
            return "uid"
        if (key := dedup.canonical_url(job.url)) and key in self._by_url:
            return "url"
        if use_fingerprint:
            fp = dedup.fingerprint(job.company, job.title, job.location)
            if fp and fp in self._by_fp:
                return "fingerprint"
        return None

    def has_uid(self, uid: str) -> bool:
        return uid in self._seen

    # -- mutation ----------------------------------------------------------- #
    def add(self, job: Job) -> None:
        """Record a posting as alerted-on, under all three of its keys."""
        now = _iso(_now())
        self._seen[job.uid] = {
            "title": job.title,
            "company": job.company,
            "url": job.url,
            "location": job.location,
            "posted_at": job.posted_at,   # the board's own time, for freshness auditing
            "source": job.source,
            "first_seen": now,
            "last_seen": now,
        }
        if (key := dedup.canonical_url(job.url)):
            self._by_url.setdefault(key, job.uid)
        if (fp := dedup.fingerprint(job.company, job.title, job.location)):
            self._by_fp.setdefault(fp, job.uid)
        self._dirty = True

    def touch(self, uid: str) -> None:
        """Mark a known posting as still listed, so pruning can tell a delisted
        job from one that is simply old."""
        rec = self._seen.get(uid)
        if rec is None:
            return
        today = _iso(_now())
        if rec.get("last_seen", "")[:10] != today[:10]:
            rec["last_seen"] = today
            self._dirty = True

    def mark_simplify_all_seeded(self) -> None:
        self.simplify_all_seeded = True
        self._dirty = True

    def is_source_seeded(self, source: str) -> bool:
        return source in self.seeded_sources

    def mark_source_seeded(self, source: str) -> None:
        if source not in self.seeded_sources:
            self.seeded_sources.add(source)
            self._dirty = True

    def prune(self, delisted_days: int) -> int:
        """Drop records for postings no board has listed in `delisted_days`.

        Keyed on last_seen, not first_seen: a long-open role stays in the store
        (and so stays deduped) however old it is, while a role that vanished
        from every board months ago cannot come back to re-notify us. Returns
        the number of records dropped. Non-positive input disables pruning.
        """
        if delisted_days <= 0:
            return 0
        cutoff = _now() - timedelta(days=delisted_days)
        stale = []
        for uid, rec in self._seen.items():
            # Records written before last_seen existed fall back to first_seen;
            # a record with neither is left alone rather than dropped on a guess.
            ts = _parse_iso(rec.get("last_seen", "")) or _parse_iso(rec.get("first_seen", ""))
            if ts is not None and ts < cutoff:
                stale.append(uid)
        for uid in stale:
            del self._seen[uid]
        if stale:
            self._reindex()
            self._dirty = True
        return len(stale)

    # -- persistence -------------------------------------------------------- #
    @property
    def dirty(self) -> bool:
        return self._dirty

    def save(self, force: bool = False) -> bool:
        """Atomically write the store. No-ops when nothing changed unless forced.
        Returns True if a write happened."""
        if not (self._dirty or force):
            return False
        payload = {
            "schema": _SCHEMA,
            "updated_at": _iso(_now()),
            "count": len(self._seen),
            "simplify_all_seeded": self.simplify_all_seeded,
            "seeded_sources": sorted(self.seeded_sources),
            "jobs": self._seen,
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        self._dirty = False
        return True

    def merge_from(self, other_path: Path) -> int:
        """Union another store file's records into this one. Returns how many
        records were added.

        Used before pushing state back to git: the remote copy may hold records
        this process never saw (a manual run, a run whose push landed while we
        were looping). Dropping those would let already-notified jobs look new
        again, so the two sides are unioned rather than one overwriting the
        other. Ours wins on a shared uid — it is at least as recent.
        """
        try:
            data = json.loads(other_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return 0
        incoming = data.get("jobs", {}) or {}
        added = 0
        for uid, rec in incoming.items():
            if uid not in self._seen:
                self._seen[uid] = rec
                added += 1
        merged_sources = set(data.get("seeded_sources") or [])
        if not merged_sources.issubset(self.seeded_sources):
            self.seeded_sources |= merged_sources
            self._dirty = True
        if data.get("simplify_all_seeded") and not self.simplify_all_seeded:
            self.simplify_all_seeded = True
            self._dirty = True
        if added:
            self._reindex()
            self._dirty = True
        return added

    def __len__(self) -> int:
        return len(self._seen)
