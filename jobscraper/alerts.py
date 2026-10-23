"""Where operational alerts go, now that they no longer go to Discord.

The Discord webhook is the *job* channel. An outage notice sitting between two
job postings is noise in the one place that should only ever carry things worth
applying to, and it trains you to skim the channel. So health alerts are routed
out of it entirely (`HEALTH_ALERT_DISCORD`, off by default).

Three sinks, cheapest first. All of them are best-effort: a scraper that cannot
file a notice must keep scraping, so every failure here is logged and swallowed
rather than raised.

* **The log** — always. Free, and the Actions run page is where you look when
  something is already suspected.
* **An Actions annotation and the job summary** — when running in Actions.
  Puts the notice on the run's own page without any API call.
* **A GitHub issue** — the only one of the three that actually *notifies*, via
  your normal GitHub notifications. One issue is reused for the life of an
  outage (reopened if closed, commented on if open) rather than filing a fresh
  one per sweep, which is what makes this safe to leave on by default.

`jobscraper health` prints the same picture on demand, which is how to get it
into a chat: ask for it and it is read out of the state file.
"""
from __future__ import annotations

import json
import os

from . import log, settings

logger = log.get()

# Marker hidden in the issue body so we can find the issue again without
# relying on its title, which a human may well rewrite.
ISSUE_MARKER = "<!-- internship-radar:health -->"
ISSUE_TITLE = "Scraper health: one or more job boards are down"


def _in_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS", "").lower() == "true"


def _annotate(text: str, level: str = "warning") -> None:
    """Emit a GitHub Actions annotation, which surfaces on the run page.

    Workflow commands are newline-delimited, so an embedded newline would end
    the command and leave the rest as plain output; they are escaped per the
    Actions spec.
    """
    if not _in_actions():
        return
    escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    print(f"::{level}::{escaped}", flush=True)


def _step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text.rstrip() + "\n\n")
    except OSError as exc:
        logger.debug("could not write step summary: %s", exc)


# --------------------------------------------------------------------------- #
# GitHub issue sink
# --------------------------------------------------------------------------- #
def _api(path: str) -> str:
    base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    return f"{base}{path}"


def _github_ready() -> tuple[str, str] | None:
    """(token, repo) when we can file an issue, else None."""
    token = (os.environ.get("HEALTH_ALERT_GITHUB_TOKEN")
             or os.environ.get("GITHUB_TOKEN", "")).strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    return (token, repo) if token and repo else None


def _gh_request(method: str, url: str, token: str, payload: dict | None = None):
    from . import http
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    kwargs = {"headers": headers, "retries": 1, "timeout": 20}
    if payload is not None:
        kwargs["json"] = payload
    return http.request(method, url, **kwargs)


def _find_open_issue(token: str, repo: str) -> dict | None:
    """The health issue, if one already exists (open or recently closed).

    Searched by marker rather than title so a renamed issue is still found, and
    a closed one is reused rather than leaving a trail of duplicates.
    """
    resp = _gh_request("GET", _api(f"/repos/{repo}/issues?state=all&per_page=30"), token)
    if resp.status_code >= 300:
        logger.debug("health issue lookup failed: HTTP %s", resp.status_code)
        return None
    for issue in resp.json():
        if issue.get("pull_request"):
            continue
        if ISSUE_MARKER in (issue.get("body") or ""):
            return issue
    return None


def _post_github_issue(text: str, resolved: bool) -> bool:
    """File or update the health issue. Returns whether anything was posted."""
    ready = _github_ready()
    if not ready:
        logger.debug("no GITHUB_TOKEN/GITHUB_REPOSITORY; skipping issue alert")
        return False
    token, repo = ready

    try:
        issue = _find_open_issue(token, repo)
        body = f"{text}\n\n{ISSUE_MARKER}"

        if issue is None:
            if resolved:
                # Nothing was ever filed, so there is nothing to close out.
                return False
            resp = _gh_request("POST", _api(f"/repos/{repo}/issues"), token,
                               {"title": ISSUE_TITLE, "body": body})
            if resp.status_code >= 300:
                logger.warning("could not open health issue: HTTP %s %s",
                               resp.status_code, resp.text[:200])
                return False
            logger.info("Opened health issue #%s", resp.json().get("number"))
            return True

        number = issue.get("number")
        _gh_request("POST", _api(f"/repos/{repo}/issues/{number}/comments"),
                    token, {"body": text})
        # An outage that comes back after the issue was closed should reopen it,
        # so the notice lands in notifications instead of in a closed thread.
        if not resolved and issue.get("state") == "closed":
            _gh_request("PATCH", _api(f"/repos/{repo}/issues/{number}"), token,
                        {"state": "open"})
        elif resolved and issue.get("state") == "open":
            _gh_request("PATCH", _api(f"/repos/{repo}/issues/{number}"), token,
                        {"state": "closed", "state_reason": "completed"})
        logger.info("Updated health issue #%s", number)
        return True
    except Exception as exc:  # noqa: BLE001 - an alert must never break a sweep
        logger.warning("health issue alert failed: %s: %s", type(exc).__name__, exc)
        return False


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def health_alert(text: str, *, resolved: bool = False) -> None:
    """Route one health notice to every configured sink except Discord.

    `resolved` marks a recovery note, which closes the issue instead of
    reopening it and annotates at notice level rather than warning.
    """
    if resolved:
        logger.info(text)
    else:
        logger.warning(text)

    _annotate(text, level="notice" if resolved else "warning")
    _step_summary(("### ✅ Scraper health recovered\n\n" if resolved
                   else "### ⚠️ Scraper health\n\n") + text)

    if settings.HEALTH_ALERT_GITHUB:
        _post_github_issue(text, resolved)


def health_snapshot(store) -> str:
    """Human-readable current health, for `jobscraper health`."""
    tracker = store.health
    lines = [
        f"Boards known: {len(tracker.adapters)}",
        f"Currently failing: {len(tracker.failing)}",
        f"Reported as down: {len(store.health_reported)}",
    ]
    if tracker.failing:
        lines.append("")
        lines.append("Failing now (consecutive failures / since first failure):")
        import time
        now = time.time()
        for name, f in sorted(tracker.failing.items(),
                              key=lambda kv: -kv[1].streak):
            from .health import _fmt_age, short_error
            flag = " [reported]" if name in store.health_reported else ""
            lines.append(f"  {name:<24} {f.adapter:<16} x{f.streak:<3} "
                         f"{_fmt_age(now - f.since):>6}  {short_error(f.error)[:60]}{flag}")
    else:
        lines.append("")
        lines.append("No board is currently failing.")
    return "\n".join(lines)


def dump_json(store) -> str:
    """Machine-readable health, for piping somewhere else."""
    return json.dumps({
        "boards_known": len(store.health.adapters),
        "failing": {
            name: {"adapter": f.adapter, "streak": f.streak,
                   "since": f.since, "error": f.error}
            for name, f in store.health.failing.items()
        },
        "reported_down": sorted(store.health_reported),
    }, indent=2, sort_keys=True)
