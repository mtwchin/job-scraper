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

**Who belongs here:** companies ranked at or above IBM (#88) on the Plonkd
software-engineering prestige ranking (plonkd.com, the successor to Prestige
Hunt), plus any company whose entry-level SWE median total compensation on
levels.fyi is over $200K, plus a few top labs and quant firms too new or too
small to be ranked (xAI, Thinking Machines, Waymo, Five Rings, Radix, ...).
Below that bar (Disney, the banks, Cisco, Intel, PayPal, ...) goes to all-SWE.

To add a company: add a row. To stop reading its board: set **On** to `no`.
Use `jobscraper discover <name|url>` to find a company's adapter + config, and
`jobscraper probe <adapter> <config>` to confirm the adapter actually parses it.
Tokens marked `(verify)` are best guesses — if a company returns 0 jobs, the
token/slug is probably wrong. See the README for how to find the right one.


## Big tech

| Company        | Adapter    | Config                                                              | On  | Notes |
|----------------|------------|--------------------------------------------------------------------|-----|-------|
| Google         | google     |                                                                    | yes | Verified — scrapes server-rendered results page |
| DeepMind       | google     | company=DeepMind                                                   | yes | Official careers page now uses Google Careers company filter |
| Meta           | meta       |                                                                    | no  | GraphQL doc_id rotates; needs maintenance to re-enable |
| Microsoft      | microsoft  |                                                                    | yes | Verified — current apply.careers.microsoft.com Eightfold search |
| LinkedIn       | smartrecruiters | id=LinkedIn3                                                       | yes | Verified via probe — SmartRecruiters board (Simplify lagged it ~9h) |
| GitHub         | custom     |                                                                    | no  | Microsoft-owned; custom careers site |
| Apple          | apple      |                                                                    | yes | Verified — server-rendered internship listings with exact posting times |
| Amazon         | amazon     |                                                                    | yes | Verified — amazon.jobs API |
| Netflix        | eightfold  | host=explore.jobs.netflix.net;domain=netflix.com                   | yes | Verified (moved off Lever to Eightfold) |
| Nvidia         | workday    | host=nvidia.wd5.myworkdayjobs.com;tenant=nvidia;site=NVIDIAExternalCareerSite | yes | Verified |
| Tesla          | custom     |                                                                    | no  | Custom careers site |
| SpaceX         | greenhouse | token=spacex                                                       | yes | Verified |
| ByteDance      | custom     |                                                                    | no  | Custom careers site |
| Uber           | workday    | host=uber.wd1.myworkdayjobs.com;tenant=uber;site=External          | no  | Workday config 422; verify site/tenant |
| Airbnb         | greenhouse | token=airbnb                                                       | yes | Verified |
| Waymo          | greenhouse | token=waymo                                                        | yes | Verified |
| Salesforce     | workday    | host=salesforce.wd12.myworkdayjobs.com;tenant=salesforce;site=External_Career_Site | yes | Verified |
| Slack          | workday    |                                                                    | no  | Salesforce-owned; Workday — need config |
| Adobe          | workday    | host=adobe.wd5.myworkdayjobs.com;tenant=adobe;site=external_experienced | yes | Verified |
| Oracle         | oracle     | host=eeho.fa.us2.oraclecloud.com;site=CX_45001                     | yes | Verified via probe — Oracle Cloud board |
| Qualcomm       | custom     |                                                                    | no  | Moved off public Workday; covered via Simplify |
| Broadcom       | workday    | host=broadcom.wd1.myworkdayjobs.com;tenant=broadcom;site=External_Career | yes | Verified via probe |
| VMware         | smartrecruiters | id=Vmware2                                                         | no  | Broadcom-owned; roles now post on Broadcom's board |
| Intuit         | workday    | host=intuit.wd1.myworkdayjobs.com;tenant=intuit;site=External      | no  | Workday config returns 401; verify site/tenant |
| IBM            | custom     |                                                                    | no  | Custom careers site (cutoff company) |
| NASA           | custom     |                                                                    | no  | Government — USAJobs.gov |

## AI labs


| OpenAI         | ashby      | slug=openai                                                        | yes | Verified |
| Anthropic      | greenhouse | token=anthropic                                                    | yes | Verified |
| xAI            | greenhouse | token=xai                                                          | yes | Verified |
| Scale AI       | greenhouse | token=scaleai                                                      | yes | Verified |
| Cursor         | ashby      | slug=cursor                                                        | yes | Verified — Anysphere |
| Perplexity     | ashby      | slug=perplexity                                                    | yes | Verified |
| Thinking Machines | ashby      | slug=ThinkingMachines                                              | yes | Official Ashby board; old Greenhouse token 404s |
| Harvey         | ashby      | slug=harvey                                                        | yes | Verified |
| Cognition      | ashby      | slug=cognition                                                     | yes | Verified |
| Glean          | greenhouse | token=gleanwork                                                    | yes | Verified |
| Midjourney     | ashby      | slug=midjourney                                                    | yes | Verified via probe |
| CoreWeave      | greenhouse | token=coreweave                                                    | yes | Verified via probe; entry-level TC > $200K |

## Top-tier tech


| Stripe         | greenhouse | token=stripe                                                       | yes | Verified |
| Databricks     | greenhouse | token=databricks                                                   | yes | Verified |
| Snowflake      | ashby      | slug=snowflake                                                     | yes | Verified (fixed from bad greenhouse token) |
| Palantir       | lever      | slug=palantir                                                      | yes | Verified |
| Coinbase       | greenhouse | token=coinbase                                                     | yes | Verified |
| Robinhood      | greenhouse | token=robinhood                                                    | yes | Verified |
| Ramp           | ashby      | slug=ramp                                                          | yes | Verified |
| Plaid          | ashby      | slug=plaid                                                         | yes | Verified |
| Brex           | greenhouse | token=brex                                                         | yes | Verified |
| SoFi           | greenhouse | token=sofi                                                         | yes | Verified via probe |
| Ripple         | greenhouse | token=ripple                                                       | yes | Verified via probe |
| Block (Square) | greenhouse | token=block                                                        | yes | Verified |
| Roblox         | greenhouse | token=roblox                                                       | yes | Verified |
| DoorDash       | greenhouse | token=doordashusa                                                  | yes | Verified |
| Lyft           | greenhouse | token=lyft                                                         | yes | Verified |
| Dropbox        | greenhouse | token=dropbox                                                      | yes | Verified |
| Notion         | ashby      | slug=notion                                                        | yes | Verified |
| Airtable       | greenhouse | token=airtable                                                     | yes | Verified via probe |
| Figma          | greenhouse | token=figma                                                        | yes | Verified |
| Canva          | smartrecruiters | id=Canva                                                           | yes | Verified via probe |
| Discord        | greenhouse | token=discord                                                      | yes | Verified |
| Pinterest      | greenhouse | token=pinterest                                                    | yes | Verified |
| Snap           | custom     |                                                                    | no  | Custom careers site |
| Spotify        | lever      | slug=spotify                                                       | yes | Verified |
| Epic Games     | greenhouse | token=epicgames                                                    | yes | Verified via probe |
| Shopify        | custom     |                                                                    | no  | Custom careers site |
| Rippling       | custom     |                                                                    | no  | No public ATS API found (was bad greenhouse token) |
| Vercel         | greenhouse | token=vercel                                                       | yes | Verified |
| Anduril        | greenhouse | token=andurilindustries                                            | yes | Verified |
| Skydio         | ashby      | slug=skydio                                                        | yes | Verified |
| StubHub        | greenhouse | token=stubhubinc                                                   | yes | Verified via probe; entry-level TC > $200K |
| Bloomberg      | custom     |                                                                    | no  | Custom careers site |

## Infrastructure & enterprise


| Datadog        | greenhouse | token=datadog                                                      | yes | Verified |
| Cloudflare     | greenhouse | token=cloudflare                                                   | yes | Verified |
| CrowdStrike    | workday    | host=crowdstrike.wd5.myworkdayjobs.com;tenant=crowdstrike;site=crowdstrikecareers | yes | Verified via probe |
| Palo Alto Networks | smartrecruiters | id=PaloAltoNetworks1                                               | yes | Verified via CI probe — small SR tenant |
| Okta           | greenhouse | token=okta                                                         | yes | Verified |
| MongoDB        | greenhouse | token=mongodb                                                      | yes | Verified |
| Confluent      | ashby      | slug=confluent                                                     | yes | Verified |
| GitLab         | greenhouse | token=gitlab                                                       | yes | Verified |
| Atlassian      | smartrecruiters | id=Atlassian2                                                      | yes | Verified via CI probe — small SR tenant, main board is elsewhere |
| Asana          | greenhouse | token=asana                                                        | yes | Verified |
| Box            | greenhouse | token=boxinc                                                       | yes | Verified |
| DocuSign       | custom     |                                                                    | no  | iCIMS site (no clean API); covered via Simplify |
| HubSpot        | custom     |                                                                    | no  | Custom/JS careers site; covered via Simplify |
| ServiceNow     | smartrecruiters | id=Servicenow                                                      | yes | Verified via probe |
| Twilio         | greenhouse | token=twilio                                                       | yes | Verified via probe |
| Sentry         | ashby      | slug=sentry                                                        | yes | Verified via probe |
| Pure Storage   | greenhouse | token=purestorage                                                  | yes | Verified via probe |
| Red Hat        | workday    | host=redhat.wd5.myworkdayjobs.com;tenant=redhat;site=jobs          | yes | Verified |

## Quant / trading


| Jane Street    | greenhouse | token=janestreet                                                   | yes | Verified — quant |
| Citadel        | custom     |                                                                    | no  | Custom careers site |
| Two Sigma      | custom     |                                                                    | no  | Custom careers site |
| Hudson River Trading | custom     |                                                                    | no  | HRT — no public ATS API; custom careers site |
| Jump Trading   | greenhouse | token=jumptrading                                                  | yes | Verified — quant |
| Susquehanna (SIG) | custom     |                                                                    | no  | No public ATS board found; covered via feeds |
| D.E. Shaw      | custom     |                                                                    | no  | Custom careers site |
| Renaissance Technologies | custom     |                                                                    | no  | RenTech — custom careers site |
| Optiver        | greenhouse | token=optiverus                                                    | yes | Verified — quant |
| IMC Trading    | greenhouse | token=imc                                                          | yes | Verified — quant |
| Five Rings     | greenhouse | token=fiveringsllc                                                 | yes | Verified — quant |
| Radix Trading  | custom     |                                                                    | no  | Custom careers site |
| Tower Research | greenhouse | token=towerresearchcapital                                         | yes | Verified |
| PDT Partners   | greenhouse | token=pdtpartners                                                  | yes | Verified |
| Akuna Capital  | greenhouse | token=akunacapital                                                 | yes | Verified — quant |
| Bridgewater    | custom     |                                                                    | no  | No public ATS board found; covered via feeds |
