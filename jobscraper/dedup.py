"""Identity keys used to decide whether we've already alerted on a posting.

A single opening routinely reaches us through more than one path: a company's
own ATS *and* an aggregator that mirrors it. Those carry different source ids,
so the per-source `Job.uid` alone is not enough — before this module the same
role could (and did) get posted to Discord twice, once per path.

Three keys, cheapest and strictest first:

* ``uid``            — the per-source id. Exact re-encounter of the same listing.
* ``canonical_url``  — the apply link with cosmetic noise stripped. Two listings
                       pointing at the same URL are the same opening, whoever
                       told us about it. This is the cross-source key.
* ``fingerprint``    — company + title + location. Catches a board that reissues
                       the same opening under a fresh requisition id (a new URL),
                       which URL-matching cannot see. Location is part of the key
                       on purpose: Amazon-style postings that repeat one title
                       across several offices are distinct openings, not dupes.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlsplit

# Query parameters that actually identify the posting. Everything else (tracking,
# referral, board-source tags) is dropped so the same job linked from two places
# collapses to one key.
_MEANINGFUL_QUERY_KEYS = {
    "jobid", "job_id", "gh_jid", "id", "req", "reqid", "req_id", "jid", "pid",
    "posting", "postingid", "jobpostingid", "rid", "vacancyid", "positionid",
}

# Trailing corporate suffixes stripped when normalizing a company name, so
# "Stripe, Inc." and "Stripe" agree.
_COMPANY_SUFFIXES = (
    "incorporated", "inc", "llc", "ltd", "limited", "corporation", "corp",
    "company", "co", "labs", "technologies", "technology", "holdings", "group",
)

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def canonical_url(url: str) -> str:
    """A stable, comparable form of an apply link.

    Lowercases the host, drops ``www.``, discards the scheme, normalizes a
    trailing slash, and keeps only query parameters that identify the posting.
    Returns "" for anything unusable, which callers must treat as "no opinion"
    rather than as a match — otherwise every url-less job would collide.
    """
    if not url or not url.strip():
        return ""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""

    host = (parts.netloc or "").lower()
    if "@" in host:  # strip any userinfo
        host = host.rsplit("@", 1)[-1]
    host = re.sub(r":(80|443)$", "", host)
    if host.startswith("www."):
        host = host[4:]

    path = (parts.path or "").rstrip("/")
    if not host and not path:
        return ""

    kept = sorted(
        (k.lower(), v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() in _MEANINGFUL_QUERY_KEYS and v
    )
    query = "&".join(f"{k}={v}" for k, v in kept)
    return f"{host}{path.lower()}" + (f"?{query}" if query else "")


def normalize_company(name: str) -> str:
    """Lowercase, strip parentheticals/punctuation, drop one trailing suffix."""
    name = re.sub(r"\(.*?\)", " ", (name or "").lower())
    name = _NON_ALNUM.sub(" ", name).strip()
    for suffix in _COMPANY_SUFFIXES:
        if name.endswith(" " + suffix):
            name = name[: -(len(suffix) + 1)].strip()
            break
    return _WS.sub(" ", name)


def normalize_title(title: str) -> str:
    """Lowercase and collapse punctuation so cosmetic title edits still match.

    Also strips a trailing requisition id some boards append to the title
    ("Software Engineer Intern (R12345)" / "... - JR0099"), which would
    otherwise make one reposted opening look like a new one.
    """
    t = (title or "").lower()
    t = re.sub(r"[\(\[\{]?\b(?:job\s*)?(?:r|jr|req|id)[-_ ]?\d{3,}\b[\)\]\}]?", " ", t)
    t = _NON_ALNUM.sub(" ", t)
    return _WS.sub(" ", t).strip()


def normalize_location(location: str) -> str:
    """Normalize a location for comparison.

    Multi-location strings are order-insensitive: a board that lists
    "Seattle, WA; Austin, TX" one day and the reverse the next is describing the
    same opening. Empty stays empty — callers treat that as "unknown", never as
    a match with another unknown.
    """
    loc = (location or "").lower()
    parts = [_WS.sub(" ", _NON_ALNUM.sub(" ", p)).strip() for p in re.split(r"[;|/]", loc)]
    parts = [p for p in parts if p]
    return "|".join(sorted(parts))


def fingerprint(company: str, title: str, location: str) -> str:
    """Company + title + location key, or "" when too thin to be trustworthy.

    Requires a company, a title, *and* a location. Without a location we cannot
    tell a genuine second opening from a repost, so we decline to guess and
    return "" — the caller then falls back to url/uid matching only. Being
    slightly noisy beats silently swallowing a real posting.
    """
    c, t, l = normalize_company(company), normalize_title(title), normalize_location(location)
    if not c or not t or not l:
        return ""
    return f"{c}::{t}::{l}"


class KeySet:
    """In-memory set of job identities, used to collapse duplicates inside a
    single collection pass.

    The persistent store answers "did we already alert on this?"; this answers
    "have we already picked this up earlier in *this* pass?" — needed because a
    company's own ATS and an aggregator mirroring it are both fetched in the
    same pass, and the run-level `uid` differs between them.
    """

    __slots__ = ("_uids", "_urls", "_fps", "use_fingerprint")

    def __init__(self, use_fingerprint: bool = True):
        self._uids: set[str] = set()
        self._urls: set[str] = set()
        self._fps: set[str] = set()
        self.use_fingerprint = use_fingerprint

    def __contains__(self, job) -> bool:
        if job.uid in self._uids:
            return True
        if (key := canonical_url(job.url)) and key in self._urls:
            return True
        if self.use_fingerprint:
            fp = fingerprint(job.company, job.title, job.location)
            if fp and fp in self._fps:
                return True
        return False

    def add(self, job) -> None:
        self._uids.add(job.uid)
        if (key := canonical_url(job.url)):
            self._urls.add(key)
        if (fp := fingerprint(job.company, job.title, job.location)):
            self._fps.add(fp)

    def __len__(self) -> int:
        return len(self._uids)
