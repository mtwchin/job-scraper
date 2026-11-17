"""Reset the per-process caches that would otherwise leak between tests."""
import pytest

from jobscraper import main, settings
from jobscraper.adapters import ats


def _reset():
    main._backoff.clear()
    ats._workday_locations.clear()
    ats._workday_next.clear()
    ats._workday_cooling.clear()
    ats._workday_all_until = 0.0


@pytest.fixture(autouse=True)
def _fresh_process_state(monkeypatch):
    _reset()
    # Tests that care about Workday pacing set a gap themselves.
    monkeypatch.setattr(settings, "WORKDAY_MIN_GAP_SECONDS", 0.0)
    yield
    _reset()
