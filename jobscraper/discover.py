"""Detect which ATS a company uses and print a ready-to-paste companies.md row.

This is how you "fix" a disabled company (or add a new one): point it at a name,
a careers URL, or an ATS URL and it figures out the adapter + config and verifies
the endpoint actually returns jobs.

    python -m jobscraper.discover "Stripe"
    python -m jobscraper.discover stripe airbnb figma
    python -m jobscraper.discover https://job-boards.greenhouse.io/databricks
    python -m jobscraper.discover https://cisco.wd5.myworkdayjobs.com/en-US/Cisco_Careers

For Workday/custom SPAs that hide their board, open the careers page, copy the
real board URL from the address bar (or DevTools → Network), and pass that.
"""
from __future__ import annotations

import re
import sys

from . import http


# --- direct API probes (return (adapter, config, job_count) or None) -------
def try_greenhouse(slug: str):
    r = http.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false", retries=0)
    if r.ok and r.json().get("jobs"):
        return ("greenhouse", f"token={slug}", len(r.json()["jobs"]))
    return None


def try_lever(slug: str):
    r = http.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", retries=0)
    if r.ok and isinstance(r.json(), list) and r.json():
        return ("lever", f"slug={slug}", len(r.json()))
    return None


def try_ashby(slug: str):
    r = http.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", retries=0)
    if r.ok and r.json().get("jobs"):
        return ("ashby", f"slug={slug}", len(r.json()["jobs"]))
    return None


def try_workday(host: str, tenant: str, site: str):
    api = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    r = http.post(
        api,
        json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": "software"},
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        retries=0,
    )
    if r.ok:
        return ("workday", f"host={host};tenant={tenant};site={site}", r.json().get("total", "?"))
    return None


# --- URL parsing -----------------------------------------------------------
def from_url(url: str):
    m = re.search(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_]+)", url, re.I)
    if m:
        return try_greenhouse(m.group(1))
    m = re.search(r"jobs\.lever\.co/([a-z0-9-]+)", url, re.I)
    if m:
        return try_lever(m.group(1))
    m = re.search(r"(?:jobs\.ashbyhq\.com|ashbyhq\.com/[^/]*job-board[^/]*)/([a-z0-9-]+)", url, re.I)
    if m:
        return try_ashby(m.group(1))
    m = re.search(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-zA-Z-]+/)?([A-Za-z0-9_-]+)", url, re.I)
    if m:
        host, site = m.group(1), m.group(2)
        return try_workday(host, host.split(".")[0], site)
    # Otherwise fetch the page and look for an embedded ATS reference.
    try:
        html = http.get(url, retries=0).text
    except Exception:
        return None
    for pat, fn in [
        (r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_]+)", try_greenhouse),
        (r"jobs\.lever\.co/([a-z0-9-]+)", try_lever),
        (r"jobs\.ashbyhq\.com/([a-z0-9-]+)", try_ashby),
    ]:
        m = re.search(pat, html, re.I)
        if m and (hit := fn(m.group(1))):
            return hit
    m = re.search(r"([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-zA-Z-]+/)?([A-Za-z0-9_-]+)", html, re.I)
    if m:
        host, site = m.group(1), m.group(2)
        return try_workday(host, host.split(".")[0], site)
    return None


# --- name -> slug guesses --------------------------------------------------
def from_name(name: str):
    base = re.sub(r"[^a-z0-9]+", "", name.lower())
    dashed = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slugs = list(dict.fromkeys([base, dashed, f"{base}careers", f"{base}us", f"{base}inc", f"{base}jobs"]))
    for slug in slugs:
        for fn in (try_greenhouse, try_lever, try_ashby):
            try:
                if hit := fn(slug):
                    return hit
            except Exception:
                continue
    return None


def discover(target: str):
    return from_url(target) if "://" in target or "myworkdayjobs" in target else from_name(target)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for target in argv:
        hit = discover(target)
        if hit:
            adapter, config, n = hit
            print(f"\n✅ {target}")
            print(f"   adapter={adapter}  {config}  ({n} jobs)")
            print(f"   companies.md row:")
            print(f"   | {target[:14]:<14} | {adapter:<10} | {config:<40} | yes | Verified |")
        else:
            print(f"\n❌ {target}: no public Greenhouse/Lever/Ashby/Workday board found.")
            print("   It's likely a custom/JS-rendered site. Open its careers page, copy")
            print("   the real board URL (address bar or DevTools→Network), and pass that.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
