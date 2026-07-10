"""Decide whether a job title is a SWE/SDE intern or new-grad role we care about."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .models import Job

# Must look like a software-engineering role. Includes software-adjacent titles
# (systems/platform/infra/backend/frontend/full-stack engineer) since many SWE
# intern roles don't literally say "software" in the title.
SWE_PATTERNS = [
    r"software\s+engineer",
    r"software\s+developer",
    r"software\s+development\s+engineer",
    r"\bsde\b",
    r"\bswe\b",
    r"software\s+engineering",
    r"member\s+of\s+technical\s+staff",
    r"\bprogrammer\b",
    r"systems?\s+engineer",
    r"platform\s+engineer",
    r"infrastructure\s+engineer",
    r"back[\s-]?end\s+engineer",
    r"front[\s-]?end\s+engineer",
    r"full[\s-]?stack\s+engineer",
    r"distributed\s+systems",
    r"forward\s+deployed\s+engineer",
]

# Internship signals.
INTERN_PATTERNS = [
    r"\bintern\b",
    r"\binternship\b",
    r"\bco-?op\b",
    r"\bplacement\b",
]

# New-grad / entry-level full-time signals. Besides explicit "new grad" wording,
# entry-level FT roles often carry a level-1 or junior/associate marker instead
# ("Software Engineer I", "SDE 1", "Associate Software Engineer"). Plain
# "Software Engineer" with no level marker stays excluded — it's indistinguishable
# from mid-level by title alone.
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
    r"\bjunior\b",
    r"\bjr\.?\s+(software|engineer|developer)",
    r"\bassociate\b",
    r"\b(engineer|developer)\s+[i1]\b",   # Engineer I / Engineer 1 (not II/III)
    r"\b(sde|swe)\s*[i1]\b",              # SDE I, SDE1, SWE 1
]

# Seasons used for off-season filtering.
SUMMER = re.compile(r"\bsummer\b", re.I)
OTHER_SEASON = re.compile(r"\b(fall|autumn|winter|spring|off[\s-]?season)\b", re.I)

# Titles that are clearly not what an applicant wants.
NEGATIVE_PATTERNS = [
    r"\bsenior\b",
    r"\bsr\.?\b",
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


# --------------------------------------------------------------------------- #
# Location filtering: United States + Canada only
# --------------------------------------------------------------------------- #
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
CA_PROVINCES = {"ON", "QC", "BC", "AB", "MB", "SK", "NS", "NB", "NL", "PE", "NT", "YT", "NU"}

# Strong positive signals for North America.
_NA_COUNTRY = re.compile(r"\b(united states|u\.?s\.?a?\.?|usa|canada)\b", re.I)
_NA_PREFIX = re.compile(r"\b(us|ca)-", re.I)  # US-Remote, US-WA-Bellevue, CA-Ontario
_NA_NAMES = re.compile(
    r"\b("
    r"san francisco|new york|seattle|mountain view|sunnyvale|palo alto|san jose|"
    r"los angeles|san diego|austin|chicago|boston|cambridge|atlanta|denver|boulder|"
    r"portland|washington|redmond|bellevue|menlo park|cupertino|irvine|dallas|"
    r"houston|pittsburgh|durham|raleigh|miami|phoenix|detroit|minneapolis|"
    r"philadelphia|arlington|reston|herndon|santa clara|bentonville|"
    r"toronto|vancouver|montreal|ottawa|waterloo|calgary|edmonton|mississauga|kitchener"
    r")\b",
    re.I,
)

# Clearly-not-North-America signals.
_FOREIGN = re.compile(
    r"\b("
    # countries
    r"united kingdom|england|scotland|ireland|india|china|japan|singapore|australia|"
    r"germany|france|netherlands|sweden|switzerland|denmark|norway|finland|poland|"
    r"spain|italy|israel|brazil|mexico|korea|taiwan|hong kong|new zealand|austria|"
    r"belgium|portugal|romania|czech|hungary|ukraine|turkey|emirates|saudi|egypt|"
    r"south africa|argentina|chile|colombia|vietnam|thailand|malaysia|indonesia|"
    r"philippines|serbia|iceland|"
    # country codes
    r"chn|gbr|ind|jpn|sgp|aus|deu|fra|nld|swe|che|dnk|pol|esp|ita|isr|kor|twn|hkg|"
    # cities
    r"london|dublin|bangalore|bengaluru|hyderabad|pune|gurgaon|gurugram|chennai|"
    r"mumbai|delhi|noida|beijing|shanghai|shenzhen|guangzhou|hangzhou|tokyo|osaka|"
    r"seoul|sydney|melbourne|berlin|munich|paris|amsterdam|stockholm|zurich|zug|"
    r"geneva|copenhagen|oslo|helsinki|warsaw|krakow|madrid|barcelona|milan|rome|"
    r"tel aviv|herzliya|yokneam|haifa|taipei|sao paulo|belgrade|reykjavik|brno|prague"
    r")\b",
    re.I,
)
_FOREIGN_PREFIX = re.compile(r"\b(uk|de|fr|nl|se|ch|dk|pl|es|it|il|in|jp|sg|au|cn)-", re.I)
_TOKEN_CODE = re.compile(r"\b([A-Z]{2})\b\.?\s*$")


def in_north_america(location: str, include_unknown: bool = True) -> bool:
    """True if the location string looks like US/Canada (or is unknown & allowed)."""
    if not location or not location.strip():
        return include_unknown
    loc = location.strip()

    # Positive North-America signals win (a multi-location listing that includes
    # any US/CA office counts as relevant).
    if _NA_COUNTRY.search(loc) or _NA_PREFIX.search(loc) or _NA_NAMES.search(loc):
        return True
    for token in re.split(r"[,/|;]", loc):
        m = _TOKEN_CODE.search(token.strip())
        if m and (m.group(1) in US_STATES or m.group(1) in CA_PROVINCES):
            return True

    # Clearly foreign.
    if _FOREIGN.search(loc) or _FOREIGN_PREFIX.search(loc):
        return False

    # e.g. "4 Locations", bare "Remote" — caller decides.
    return include_unknown


# --------------------------------------------------------------------------- #
# Recency: parse a posting date
# --------------------------------------------------------------------------- #
_REL_DAYS = re.compile(r"(\d+)\+?\s*day", re.I)
_REL_MONTHS = re.compile(r"(\d+)\+?\s*month", re.I)


def parse_posted(posted_at: str) -> tuple[datetime, bool] | None:
    """Parse a posting date. Returns (datetime_utc, exact) or None.

    `exact` is True when we know the actual time of day (ISO timestamps, epoch
    millis) — those let us show a to-the-minute "posted N minutes ago". It's
    False for day-granularity sources ("May 6, 2026") and Workday's relative
    strings ("Posted Today" / "Posted N Days Ago"), where we only know the day.
    Handles: ISO 8601, epoch ms/s, "Mon D, YYYY", "Today"/"Yesterday"/"N days ago".
    """
    if not posted_at:
        return None
    s = str(posted_at).strip()
    now = datetime.now(timezone.utc)

    # Epoch milliseconds (Lever) or seconds — exact.
    if s.isdigit():
        try:
            ts = int(s)
            if ts > 1_000_000_000_000:  # ms
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc), True
        except (ValueError, OverflowError, OSError):
            return None

    # ISO 8601 (Greenhouse, Ashby) — exact if it carries a time component.
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt, ("T" in s or " " in s.strip())
    except ValueError:
        pass

    low = s.lower()
    if "today" in low or "just posted" in low:
        return now, False
    if "yesterday" in low:
        return now - timedelta(days=1), False
    if (m := _REL_DAYS.search(low)):
        return now - timedelta(days=int(m.group(1))), False
    if (m := _REL_MONTHS.search(low)):
        return now - timedelta(days=int(m.group(1)) * 30), False

    cleaned = re.sub(r"\s+", " ", s)
    for fmt in ("%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc), False
        except ValueError:
            continue

    return None


def posted_age_days(posted_at: str) -> int | None:
    """How many days ago was this posted? None if undeterminable."""
    parsed = parse_posted(posted_at)
    if parsed is None:
        return None
    dt, _ = parsed
    return max((datetime.now(timezone.utc) - dt).days, 0)


def is_recent(posted_at: str, max_days: int) -> bool:
    """Was this posted within the last `max_days`?

    For boards that give an exact timestamp (Greenhouse/Lever/Ashby/most), this is
    a precise rolling window — max_days=1 means strictly the last 24 hours. For
    day-granularity boards (Amazon date, Workday "Posted N Days Ago") we can only
    compare whole days. Unknown/unparseable dates return True (never dropped on a
    guess — dedup + the 5-min cadence already keep those fresh).
    """
    parsed = parse_posted(posted_at)
    if parsed is None:
        return True
    dt, exact = parsed
    now = datetime.now(timezone.utc)
    if exact:
        return (now - dt) <= timedelta(days=max_days)
    return (now - dt).days <= max_days


def posted_instant(posted_at: str) -> datetime | None:
    """The exact posting datetime, only when we know the time of day."""
    parsed = parse_posted(posted_at)
    if parsed is None:
        return None
    dt, exact = parsed
    return dt if exact else None


def humanize_posted(posted_at: str) -> str:
    """Coarse human string for day-granularity sources ('today', '3 days ago')."""
    parsed = parse_posted(posted_at)
    if parsed is None:
        return ""
    dt, _ = parsed
    days = (datetime.now(timezone.utc) - dt).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days ago"
