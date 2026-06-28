"""Decide whether a job title is a SWE/SDE intern or new-grad role we care about."""
from __future__ import annotations

import re

from .models import Job

# Must look like a software-engineering role.
SWE_PATTERNS = [
    r"software\s+engineer",
    r"software\s+developer",
    r"software\s+development\s+engineer",
    r"\bsde\b",
    r"\bswe\b",
    r"software\s+engineering",
    r"member\s+of\s+technical\s+staff",
    r"\bprogrammer\b",
]

# Internship signals.
INTERN_PATTERNS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bplacement\b",
]

# New-grad / entry-level signals.
NEW_GRAD_PATTERNS = [
    r"new\s+grad",
    r"new\s+graduate",
    r"recent\s+graduate",
    r"university\s+grad",
    r"early\s+career",
    r"early\s+in\s+career",
    r"entry[\s-]level",
    r"\bcampus\b",
    r"\bgrad(uate)?\s+(software|engineer|program|rotation)",
]

# Seasons used for off-season filtering.
SUMMER = re.compile(r"\bsummer\b", re.I)
OTHER_SEASON = re.compile(r"\b(fall|autumn|winter|spring|off[\s-]?season)\b", re.I)

# Titles that are clearly not what an applicant wants.
NEGATIVE_PATTERNS = [
    r"\bsenior\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\bmanager\b",
    r"\bdirector\b",
    r"\bphd\b",
    r"\bii+\b",       # level II / III
    r"\b(l[3-9]|sde\s*[2-9])\b",
]

_swe = [re.compile(p, re.I) for p in SWE_PATTERNS]
_intern = [re.compile(p, re.I) for p in INTERN_PATTERNS]
_newgrad = [re.compile(p, re.I) for p in NEW_GRAD_PATTERNS]
_negative = [re.compile(p, re.I) for p in NEGATIVE_PATTERNS]


def _any(patterns, text: str) -> bool:
    return any(p.search(text) for p in patterns)


def is_swe(title: str) -> bool:
    return _any(_swe, title)


def role_type(title: str) -> str | None:
    """Return 'intern', 'new_grad', or None."""
    if _any(_intern, title):
        return "intern"
    if _any(_newgrad, title):
        return "new_grad"
    return None


def matches(job: Job, role_types: set[str], off_season_only: bool) -> bool:
    title = job.title or ""
    if not is_swe(title):
        return False

    rtype = role_type(title)
    if rtype is None or rtype not in role_types:
        return False

    # Drop senior/staff/etc. — but never let a negative kill an explicit intern,
    # since "Intern" already implies junior and some titles say "Engineer II Intern".
    if rtype == "new_grad" and _any(_negative, title):
        return False

    if off_season_only and rtype == "intern":
        # Exclude only if it's explicitly Summer and nothing else.
        if SUMMER.search(title) and not OTHER_SEASON.search(title):
            return False

    return True
