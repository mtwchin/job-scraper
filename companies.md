# Tracked Companies (FAANG+)

This file is the **source of truth** for which companies the scraper checks.
It is parsed by `jobscraper/companies.py` — keep the table format intact.

## Columns

- **Company** — display name shown in Discord.
- **Adapter** — which fetcher to use: `amazon`, `microsoft`, `apple`, `google`,
  `meta`, `greenhouse`, `lever`, `ashby`, `workday`, `eightfold`,
  `smartrecruiters`, `workable`, `recruitee`, or `oracle`.
- **Config** — `key=value` pairs separated by `;`. Empty for custom adapters
  (amazon/microsoft/apple/google/meta). Required for the generic adapters:
  - `greenhouse` → `token=<board_token>`  (e.g. the slug in boards.greenhouse.io/<token>)
  - `lever` → `slug=<company_slug>`        (e.g. the slug in jobs.lever.co/<slug>)
  - `ashby` → `slug=<company_slug>`        (e.g. the slug in jobs.ashbyhq.com/<slug>)
  - `workday` → `host=<sub.domain>;tenant=<tenant>;site=<site>`
  - `smartrecruiters` → `id=<company identifier>` (CamelCase, often with a trailing digit)
  - `workable` → `slug=<account slug>`
  - `recruitee` → `slug=<company slug>`
  - `oracle` → `host=<sub.domain>;site=<site number>`
- **On** — `yes` to read this company's own board, `no` to skip the board (see below).
- **Notes** — anything; ignored by the parser.

This list *is* the FAANG+ channel: every row here, on or off, alerts to
`DISCORD_WEBHOOK_URL`. **On** only decides whether we read the company's own
board; a row set to `no` still gets its roles from the aggregator feeds (that is
how Tesla, Citadel etc. are covered). Every company *not* listed here goes to
the all-SWE channel instead, so to demote a company, delete its row.

To add a company: add a row. To stop reading its board: set **On** to `no`.
Use `jobscraper discover <name|url>` to find a company's adapter + config, and
`jobscraper probe <adapter> <config>` to confirm the adapter actually parses it.
Tokens marked `(verify)` are best guesses — if a company returns 0 jobs, the
token/slug is probably wrong. See the README for how to find the right one.

## Big tech

| Company        | Adapter    | Config                                                              | On  | Notes |
|----------------|------------|--------------------------------------------------------------------|-----|-------|
| Amazon         | amazon     |                                                                    | yes | Verified — amazon.jobs API |
| Google         | google     |                                                                    | yes | Verified — scrapes server-rendered results page |
| DeepMind       | google     | company=DeepMind                                                   | yes | Official careers page now uses Google Careers company filter |
| Meta           | meta       |                                                                    | no  | GraphQL doc_id rotates; needs maintenance to re-enable |
| Microsoft      | microsoft  |                                                                    | yes | Verified — current apply.careers.microsoft.com Eightfold search |
| LinkedIn       | smartrecruiters | id=LinkedIn3                                                       | yes | Verified via probe — SmartRecruiters board (Simplify lagged it ~9h) |
| Apple          | apple      |                                                                    | yes | Verified — server-rendered internship listings with exact posting times |
| Netflix        | eightfold  | host=explore.jobs.netflix.net;domain=netflix.com                   | yes | Verified (moved off Lever to Eightfold) |
| Nvidia         | workday    | host=nvidia.wd5.myworkdayjobs.com;tenant=nvidia;site=NVIDIAExternalCareerSite | yes | Verified |
| Tesla          | custom     |                                                                    | no  | Custom careers site |
| SpaceX         | greenhouse | token=spacex                                                       | yes | Verified |
| ByteDance      | custom     |                                                                    | no  | Custom careers site |
| Uber           | workday    | host=uber.wd1.myworkdayjobs.com;tenant=uber;site=External          | no  | Workday config 422; verify site/tenant |
| Airbnb         | greenhouse | token=airbnb                                                       | yes | Verified |
| Waymo          | greenhouse | token=waymo                                                        | yes | Verified |

## AI labs

| OpenAI         | ashby      | slug=openai                                                        | yes | Verified |
| Anthropic      | greenhouse | token=anthropic                                                    | yes | Verified |
| Scale AI       | greenhouse | token=scaleai                                                      | yes | Verified |
| Cursor         | ashby      | slug=cursor                                                        | yes | Verified — Anysphere |
| Perplexity     | ashby      | slug=perplexity                                                    | yes | Verified |
| Thinking Machines | ashby   | slug=ThinkingMachines                                             | yes | Official Ashby board; old Greenhouse token 404s |

## Top-tier tech

| Stripe         | greenhouse | token=stripe                                                       | yes | Verified |
| Databricks     | greenhouse | token=databricks                                                   | yes | Verified |
| Palantir       | lever      | slug=palantir                                                      | yes | Verified |
| Snowflake      | ashby      | slug=snowflake                                                     | yes | Verified (fixed from bad greenhouse token) |
| Ramp           | ashby      | slug=ramp                                                          | yes | Verified |
| Figma          | greenhouse | token=figma                                                        | yes | Verified |
| Coinbase       | greenhouse | token=coinbase                                                     | yes | Verified |
| Robinhood      | greenhouse | token=robinhood                                                    | yes | Verified |
| DoorDash       | greenhouse | token=doordashusa                                                  | yes | Verified |
| Roblox         | greenhouse | token=roblox                                                       | yes | Verified |
| Snap           | custom     |                                                                    | no  | Custom careers site |
| Anduril        | greenhouse | token=andurilindustries                                            | yes | Verified |

## Quant / trading

| Jane Street    | greenhouse | token=janestreet                                                   | yes | Verified — quant |
| Citadel        | custom     |                                                                    | no  | Custom careers site |
| Hudson River Trading | custom     |                                                                    | no  | HRT — no public ATS API; custom careers site |
| Two Sigma      | custom     |                                                                    | no  | Custom careers site |
| D.E. Shaw      | custom     |                                                                    | no  | Custom careers site |
| Renaissance Technologies | custom     |                                                                    | no  | RenTech — custom careers site |
| Jump Trading   | greenhouse | token=jumptrading                                                  | yes | Verified — quant |
| Five Rings     | greenhouse | token=fiveringsllc                                                 | yes | Verified — quant |
| IMC Trading    | greenhouse | token=imc                                                          | yes | Verified — quant |
| Optiver        | greenhouse | token=optiverus                                                    | yes | Verified — quant |
