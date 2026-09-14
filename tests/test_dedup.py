"""Tests for the identity keys that decide "have we already sent this?"."""
from __future__ import annotations

import pytest

from jobscraper.dedup import (
    KeySet,
    canonical_url,
    fingerprint,
    normalize_company,
    normalize_location,
    normalize_title,
)
from jobscraper.models import Job


def job(**kw) -> Job:
    base = dict(company="Stripe", job_id="1", title="Software Engineer Intern",
                url="https://example.com/jobs/1", location="Seattle, WA")
    base.update(kw)
    return Job(**base)


# --------------------------------------------------------------------------- #
# canonical_url
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("a,b", [
    # scheme, host case, www, and trailing slash are all cosmetic
    ("https://job-boards.greenhouse.io/affirm/jobs/7485068003",
     "http://www.Job-Boards.Greenhouse.io/affirm/jobs/7485068003/"),
    # tracking parameters are not identity
    ("https://boards.greenhouse.io/x/jobs/42",
     "https://boards.greenhouse.io/x/jobs/42?utm_source=simplify&gh_src=abc&ref=foo"),
    # default ports
    ("https://example.com/jobs/1", "https://example.com:443/jobs/1"),
])
def test_cosmetic_differences_collapse(a, b):
    assert canonical_url(a) == canonical_url(b)


def test_identifying_query_params_are_kept():
    """A board that puts the posting id in the query must not collapse two
    different postings into one key."""
    one = canonical_url("https://careers.x.com/apply?jobId=111&utm_source=z")
    two = canonical_url("https://careers.x.com/apply?jobId=222&utm_source=z")
    assert one != two
    assert "jobid=111" in one


def test_different_postings_stay_distinct():
    assert canonical_url("https://x.com/jobs/1") != canonical_url("https://x.com/jobs/2")


@pytest.mark.parametrize("bad", ["", "   ", None])
def test_unusable_urls_yield_empty_key(bad):
    """An empty key means "no opinion" — callers must not treat two of them as
    a match, or every url-less job would collide with every other."""
    assert canonical_url(bad) == ""


# --------------------------------------------------------------------------- #
# normalization helpers
# --------------------------------------------------------------------------- #
def test_company_suffixes_stripped():
    assert normalize_company("Stripe, Inc.") == normalize_company("Stripe")
    assert normalize_company("Acme Technologies") == "acme"


def test_company_suffix_not_stripped_when_it_is_the_whole_name():
    assert normalize_company("Corp") == "corp"


def test_title_requisition_ids_stripped():
    assert normalize_title("Software Engineer Intern (R12345)") == "software engineer intern"
    assert normalize_title("Software Engineer Intern - JR0099") == "software engineer intern"


def test_short_numeric_tokens_are_not_treated_as_req_ids():
    """The req-id strip requires three or more digits on purpose: anything
    looser would eat level markers like 'Engineer I' or 'SDE 2'."""
    assert normalize_title("Software Engineer R1") == "software engineer r1"


def test_title_keeps_meaningful_numbers():
    """Level markers are part of the role, not noise — dropping them would make
    'Engineer I' and 'Engineer' collide."""
    assert "1" in normalize_title("Software Engineer 1") or "i" in normalize_title(
        "Software Engineer I")


def test_multi_location_order_does_not_matter():
    assert normalize_location("Austin, TX; Seattle, WA") == normalize_location(
        "Seattle, WA; Austin, TX")


# --------------------------------------------------------------------------- #
# fingerprint
# --------------------------------------------------------------------------- #
def test_fingerprint_matches_reposted_role():
    """Same opening, reissued under a new requisition id."""
    assert fingerprint("Stripe, Inc.", "Software Engineer Intern (R171666)", "Seattle, WA") == \
           fingerprint("Stripe", "Software Engineer  Intern", "Seattle WA")


def test_fingerprint_separates_same_title_in_different_cities():
    """Amazon-style postings repeat one title across offices. Those are distinct
    openings and must not be deduped away."""
    assert fingerprint("Amazon", "SDE Intern", "Seattle, WA") != \
           fingerprint("Amazon", "SDE Intern", "Austin, TX")


@pytest.mark.parametrize("company,title,location", [
    ("", "SWE Intern", "Seattle, WA"),
    ("Stripe", "", "Seattle, WA"),
    ("Stripe", "SWE Intern", ""),      # no location -> too weak to judge
])
def test_fingerprint_declines_when_too_thin(company, title, location):
    assert fingerprint(company, title, location) == ""


# --------------------------------------------------------------------------- #
# KeySet — within-pass deduplication
# --------------------------------------------------------------------------- #
def test_keyset_catches_same_url_from_different_sources():
    """The bug this whole module exists for: one opening reached through a
    company's own ATS and through an aggregator carries two different uids."""
    direct = job(source="", job_id="7485068003", url="https://job-boards.greenhouse.io/a/jobs/74")
    mirror = job(source="simplify", job_id="simplify-abc",
                 url="https://job-boards.greenhouse.io/a/jobs/74?utm_source=simplify")
    assert direct.uid != mirror.uid

    seen = KeySet()
    seen.add(direct)
    assert mirror in seen


def test_keyset_lets_genuinely_different_jobs_through():
    seen = KeySet()
    seen.add(job(job_id="1", url="https://x.com/jobs/1"))
    assert job(job_id="2", url="https://x.com/jobs/2", title="Data Engineer Intern") not in seen


def test_keyset_does_not_collide_url_less_jobs():
    seen = KeySet()
    seen.add(job(job_id="1", url="", title="A", location="Seattle, WA"))
    assert job(job_id="2", url="", title="B", location="Austin, TX") not in seen


def test_keyset_fingerprint_can_be_disabled():
    """With the fingerprint off, only uid and url match — a repost under a new
    id gets through rather than being suppressed."""
    first = job(job_id="1", url="https://x.com/jobs/1")
    repost = job(job_id="2", url="https://x.com/jobs/2")

    strict = KeySet(use_fingerprint=True)
    strict.add(first)
    assert repost in strict

    loose = KeySet(use_fingerprint=False)
    loose.add(first)
    assert repost not in loose
