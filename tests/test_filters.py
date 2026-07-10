"""Tests for the matching/location/recency logic — the core of the scraper."""
from datetime import datetime, timedelta, timezone

import pytest

from jobscraper import filters
from jobscraper.models import Job


# --- role matching ---------------------------------------------------------
@pytest.mark.parametrize("title", [
    "Software Engineer Intern",
    "Software Development Engineer Intern, AWS - Fall 2026",
    "SWE Intern",
    "New Grad Software Engineer",
    "Software Engineer, Early Career",
    "Software Engineer I",
    "Software Development Engineer 1",
    "SDE I, Amazon Fulfillment",
    "Associate Software Engineer",
    "Junior Software Developer",
])
def test_matches_positive(title):
    job = Job("X", "1", title, "http://x", "New York, NY", "")
    assert filters.matches(job, {"intern", "new_grad"}, off_season_only=False)


@pytest.mark.parametrize("title", [
    "Senior Software Engineer",
    "Staff Software Engineer",
    "Product Manager Intern",          # not SWE
    "Software Engineering Manager",
    "Data Scientist, New Grad",        # not SWE
    "Software Engineer II",            # mid-level
    "Software Engineer III, Infrastructure",
    "Software Engineer",               # no level marker — ambiguous, excluded
    "Senior Associate Software Engineer",
    "Sr. Software Engineer I, Cloud Security",
])
def test_matches_negative(title):
    job = Job("X", "1", title, "http://x", "New York, NY", "")
    assert not filters.matches(job, {"intern", "new_grad"}, off_season_only=False)


def test_off_season_drops_summer_only():
    summer = Job("X", "1", "Software Engineer Intern - Summer 2027", "http://x")
    fall = Job("X", "2", "Software Engineer Intern - Fall 2026", "http://x")
    assert not filters.matches(summer, {"intern"}, off_season_only=True)
    assert filters.matches(fall, {"intern"}, off_season_only=True)


def test_role_types_respected():
    intern = Job("X", "1", "Software Engineer Intern", "http://x")
    assert filters.matches(intern, {"new_grad"}, off_season_only=False) is False
    assert filters.matches(intern, {"intern"}, off_season_only=False) is True


# --- location --------------------------------------------------------------
@pytest.mark.parametrize("loc", [
    "San Francisco, CA", "US-Remote, US-Chicago", "CA-Ontario-Toronto",
    "Seattle, Washington, USA", "Washington, D.C.", "Chicago, United States",
    "Toronto", "New York, NY",
])
def test_north_america_true(loc):
    assert filters.in_north_america(loc)


@pytest.mark.parametrize("loc", [
    "London", "Beijing, CHN", "PL-Warsaw", "Israel, Tel Aviv",
    "Zug, Switzerland", "Japan", "Singapore", "Bangalore, India",
])
def test_north_america_false(loc):
    assert not filters.in_north_america(loc)


def test_unknown_location_respects_flag():
    assert filters.in_north_america("4 Locations", include_unknown=True)
    assert not filters.in_north_america("4 Locations", include_unknown=False)
    assert filters.in_north_america("", include_unknown=True)


# --- recency / date parsing ------------------------------------------------
def _iso(**kw):
    return (datetime.now(timezone.utc) - timedelta(**kw)).isoformat()


def test_is_recent_exact_window():
    assert filters.is_recent(_iso(hours=2), 1) is True
    assert filters.is_recent(_iso(hours=23), 1) is True
    assert filters.is_recent(_iso(hours=25), 1) is False  # precise 24h for exact ts


def test_is_recent_epoch_millis():
    ms = str(int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp() * 1000))
    assert filters.is_recent(ms, 1) is True


def test_is_recent_coarse_sources():
    assert filters.is_recent("Posted Today", 1) is True
    assert filters.is_recent("Posted Yesterday", 1) is True
    assert filters.is_recent("Posted 2 Days Ago", 1) is False


def test_is_recent_unknown_kept():
    # never drop on a guess
    assert filters.is_recent("", 1) is True
    assert filters.is_recent("garbage date", 1) is True


def test_posted_instant_only_for_exact():
    assert filters.posted_instant(_iso(minutes=10)) is not None  # ISO w/ time
    assert filters.posted_instant("June 28, 2026") is None       # date-only
    assert filters.posted_instant("Posted Today") is None        # relative
