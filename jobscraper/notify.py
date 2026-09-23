"""Send new-job notifications to a Discord webhook."""
from __future__ import annotations

import time
from collections.abc import Callable

import requests

from . import http, settings
from .models import Job

_COLOR_INTERN = 0x5865F2   # blurple
_COLOR_NEWGRAD = 0x57F287  # green


class WebhookRejected(RuntimeError):
    """Discord explicitly rejected a request, so its jobs can be retried."""


def _posted_field(job: Job) -> dict | None:
    """A 'Posted' field, shown only when the board's date is plausibly fresh.
    Uses Discord's live relative timestamp when we know the exact time (most
    boards) so it reads e.g. 'Posted 6 minutes ago'; coarse 'today'/'N days ago'
    otherwise. Suppressed when the board date is stale (some boards report a
    req-creation date, not go-live), so we don't slap 'Posted 10 months ago' on a
    job that just went live — the alert itself means we just detected it."""
    from .filters import humanize_posted, posted_age_days, posted_instant

    age = posted_age_days(job.posted_at)
    if age is None or age > settings.STALE_POSTED_DAYS:
        return None
    inst = posted_instant(job.posted_at)
    value = f"<t:{int(inst.timestamp())}:R>" if inst else humanize_posted(job.posted_at)
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
    embed = {
        "title": job.title[:256],
        "url": job.url,
        "color": color,
        "author": {"name": job.company[:256]},
        "fields": fields,
    }
    if job.source == "simplify":
        embed["footer"] = {"text": "via Simplify"}
    return embed


def _post(payload: dict, webhook_url: str) -> None:
    if settings.DRY_RUN:
        return
    if not webhook_url:
        raise ValueError("Discord webhook is not configured")
    # A timed-out POST may already have been accepted by Discord. Automatic HTTP
    # retries can therefore produce duplicate messages. Only a confirmed 429 is
    # safe to retry: Discord explicitly rejected that request.
    for attempt in range(2):
        try:
            resp = http.post(webhook_url, json=payload, retries=0)
        except requests.RequestException as exc:
            # requests exceptions can contain the complete secret webhook URL.
            raise RuntimeError(f"Discord webhook request failed: {type(exc).__name__}") from None
        if resp.status_code == 429 and attempt == 0:
            try:
                retry_after = min(max(float(resp.json().get("retry_after", 1)), 0), 60)
            except (ValueError, TypeError, KeyError):
                retry_after = 1
            time.sleep(retry_after + 0.25)
            continue
        if resp.status_code == 429 or 400 <= resp.status_code < 500:
            raise WebhookRejected(f"Discord webhook returned HTTP {resp.status_code}")
        if resp.status_code >= 300:
            raise RuntimeError(f"Discord webhook returned HTTP {resp.status_code}")
        return


def notify_jobs(jobs: list[Job], webhook_url: str = "", *,
                on_batch_sent: Callable[[list[Job]], None] | None = None,
                on_batch_attempt: Callable[[list[Job]], None] | None = None,
                on_batch_rejected: Callable[[list[Job]], None] | None = None) -> None:
    """Send up to MAX_EMBEDS_PER_MESSAGE embeds per message. Defaults to the
    main webhook; pass DISCORD_WEBHOOK_URL_ALL to target the all-companies feed."""
    if not jobs:
        return
    webhook_url = webhook_url or settings.DISCORD_WEBHOOK_URL
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
        if on_batch_attempt is not None:
            on_batch_attempt(chunk)
        try:
            _post(payload, webhook_url)
        except WebhookRejected:
            if on_batch_rejected is not None:
                on_batch_rejected(chunk)
            raise
        if on_batch_sent is not None:
            on_batch_sent(chunk)
        time.sleep(0.4)  # be gentle with the webhook


def notify_summary(text: str, webhook_url: str = "") -> None:
    _post({"username": "Internship Radar", "content": text[:2000]}, webhook_url or settings.DISCORD_WEBHOOK_URL)
