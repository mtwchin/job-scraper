"""Reset the per-process caches that would otherwise leak between tests."""
import pytest

from jobscraper import main
from jobscraper.adapters import ats


@pytest.fixture(autouse=True)
def _fresh_process_state():
    main._backoff.clear()
    ats._workday_locations.clear()
    yield
    main._backoff.clear()
    ats._workday_locations.clear()
