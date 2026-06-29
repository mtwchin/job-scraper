"""Send new-job notifications to a Discord webhook."""
from __future__ import annotations

import time

from . import http, settings
from .models import Job

_COLOR_INTERN = 0x5865F2   # blurple
_COLOR_NEWGRAD = 0x57F287  # green


def _posted_field(job: Job) -> dict | None:
    """A 'Posted' field. Uses Discord's live relative timestamp when we know the
    exact time (most boards), so it reads e.g. 'Posted 6 minutes ago' and keeps
    updating; falls back to a coarse 'today'/'N days ago' otherwise."""
    from .filters import humanize_posted, posted_instant

    inst = posted_instant(job.posted_at)
    if inst is not None:
        value = f"<t:{int(inst.timestamp())}:R>"  # Discord renders "N minutes ago"
    else:
        value = humanize_posted(job.posted_at)
    if not value:
        return None
    return {"name": "🕐 Posted", "value": value, "inline": True}


def _embed(job: Job) -> dict:
    from .filters import role_type

    rtype = role_type(job.title) or ""
    color = _COLOR_NEWGRAD if rtype == "new_grad" else _COLOR_INTERN
    fields = []
    if job.location:
        fields.append({"name": "📍 Location", "value": job.location[:1024], "inline": True})
    if (posted := _posted_field(job)):
        fields.append(posted)
    return {
        "title": job.title[:256],
        "url": job.url,
        "color": color,
        "author": {"name": job.company[:256]},
        "fields": fields,
    }


def _post(payload: dict) -> None:
    if settings.DRY_RUN or not settings.DISCORD_WEBHOOK_URL:
        return
    resp = http.post(settings.DISCORD_WEBHOOK_URL, json=payload)
    # Discord rate limit: back off and retry once.
    if resp.status_code == 429:
        retry_after = 1.0
        try:
            retry_after = float(resp.json().get("retry_after", 1.0))
        except Exception:
            pass
        time.sleep(retry_after + 0.25)
        http.post(settings.DISCORD_WEBHOOK_URL, json=payload)
    elif resp.status_code >= 300:
        print(f"[notify] Discord returned {resp.status_code}: {resp.text[:300]}")


def notify_jobs(jobs: list[Job]) -> None:
    """Send up to MAX_EMBEDS_PER_MESSAGE embeds per message."""
    if not jobs:
        return
    batch_size = settings.MAX_EMBEDS_PER_MESSAGE
    for i in range(0, len(jobs), batch_size):
        chunk = jobs[i : i + batch_size]
        payload = {
            "username": "Internship Radar",
            "content": f"🚨 **{len(chunk)} new role(s) just opened**"
            if i == 0 and len(jobs) <= batch_size
            else None,
            "embeds": [_embed(j) for j in chunk],
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        _post(payload)
        time.sleep(0.4)  # be gentle with the webhook


def notify_summary(text: str) -> None:
    _post({"username": "Internship Radar", "content": text[:2000]})
