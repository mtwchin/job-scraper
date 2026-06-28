# Tracked Companies

This file is the **source of truth** for which companies the scraper checks.
It is parsed by `jobscraper/companies.py` — keep the table format intact.

## Columns

- **Company** — display name shown in Discord.
- **Adapter** — which fetcher to use: `amazon`, `microsoft`, `apple`, `google`,
  `meta`, `greenhouse`, `lever`, or `workday`.
- **Config** — `key=value` pairs separated by `;`. Empty for custom adapters
  (amazon/microsoft/apple/google/meta). Required for the generic adapters:
  - `greenhouse` → `token=<board_token>`  (e.g. the slug in boards.greenhouse.io/<token>)
  - `lever` → `slug=<company_slug>`        (e.g. the slug in jobs.lever.co/<slug>)
  - `ashby` → `slug=<company_slug>`        (e.g. the slug in jobs.ashbyhq.com/<slug>)
  - `workday` → `host=<sub.domain>;tenant=<tenant>;site=<site>`
- **On** — `yes` to check this company, `no` to skip it.
- **Notes** — anything; ignored by the parser.

To add a company: add a row. To pause one: set **On** to `no`.
Tokens marked `(verify)` are best guesses — if a company returns 0 jobs, the
token/slug is probably wrong. See the README for how to find the right one.

## Top tech — SWE/SDE intern & new-grad sources

| Company        | Adapter    | Config                                                              | On  | Notes |
|----------------|------------|--------------------------------------------------------------------|-----|-------|
| Amazon         | amazon     |                                                                    | yes | Verified — amazon.jobs API |
| Google         | google     |                                                                    | yes | Verified — scrapes server-rendered results page |
| Meta           | meta       |                                                                    | no  | GraphQL doc_id rotates; needs maintenance to re-enable |
| Microsoft      | microsoft  |                                                                    | no  | Old gcsservices API is dead (cert/host gone). Needs a new endpoint |
| Apple          | apple      |                                                                    | no  | jobs.apple.com needs a JS-rendered CSRF token; not scrapable headless |
| Netflix        | lever      | slug=netflix                                                       | yes | Verified |
| Palantir       | lever      | slug=palantir                                                      | yes | Verified |
| Plaid          | ashby      | slug=plaid                                                         | yes | Verified |
| OpenAI         | ashby      | slug=openai                                                        | yes | Verified |
| Ramp           | ashby      | slug=ramp                                                          | yes | Verified |
| Notion         | ashby      | slug=notion                                                        | yes | Verified |
| Stripe         | greenhouse | token=stripe                                                       | yes | Verified |
| Databricks     | greenhouse | token=databricks                                                   | yes | Verified |
| Coinbase       | greenhouse | token=coinbase                                                     | yes | Verified |
| Robinhood      | greenhouse | token=robinhood                                                    | yes | Verified |
| Airbnb         | greenhouse | token=airbnb                                                       | yes | Verified |
| Dropbox        | greenhouse | token=dropbox                                                      | yes | Verified |
| Reddit         | greenhouse | token=reddit                                                       | yes | Verified |
| Pinterest      | greenhouse | token=pinterest                                                    | yes | Verified |
| DoorDash       | greenhouse | token=doordashusa                                                  | yes | Verified |
| Instacart      | greenhouse | token=instacart                                                    | yes | Verified |
| Lyft           | greenhouse | token=lyft                                                         | yes | Verified |
| Brex           | greenhouse | token=brex                                                         | yes | Verified |
| Figma          | greenhouse | token=figma                                                        | yes | Verified |
| Discord        | greenhouse | token=discord                                                      | yes | Verified |
| Anthropic      | greenhouse | token=anthropic                                                    | yes | Verified |
| Scale AI       | greenhouse | token=scaleai                                                      | yes | Verified |
| Cloudflare     | greenhouse | token=cloudflare                                                   | yes | Verified |
| Roblox         | greenhouse | token=roblox                                                       | yes | Verified |
| Block (Square) | greenhouse | token=block                                                        | yes | Verified |
| Affirm         | greenhouse | token=affirm                                                       | yes | Verified |
| Asana          | greenhouse | token=asana                                                        | yes | Verified |
| Samsara        | greenhouse | token=samsara                                                      | yes | Verified |
| Nvidia         | workday    | host=nvidia.wd5.myworkdayjobs.com;tenant=nvidia;site=NVIDIAExternalCareerSite | yes | Verified |
| Salesforce     | workday    | host=salesforce.wd12.myworkdayjobs.com;tenant=salesforce;site=External_Career_Site | yes | Verified |
| Adobe          | workday    | host=adobe.wd5.myworkdayjobs.com;tenant=adobe;site=external_experienced | yes | Verified |
| PayPal         | workday    | host=paypal.wd1.myworkdayjobs.com;tenant=paypal;site=jobs          | yes | Verified |
| DeepMind       | greenhouse | token=deepmind                                                     | yes | Verified — prestige #3 |
| Jane Street    | greenhouse | token=janestreet                                                   | yes | Verified — quant |
| Hudson R.T.    | custom     |                                                                    | no  | HRT — no public ATS API; custom careers site |
| Citadel        | custom     |                                                                    | no  | Custom careers site |
| Jump Trading   | greenhouse | token=jumptrading                                                  | yes | Verified — quant |
| Two Sigma      | custom     |                                                                    | no  | Custom careers site |
| xAI            | greenhouse | token=xai                                                          | yes | Verified |
| Renaissance    | custom     |                                                                    | no  | RenTech — custom careers site |
| Intel          | workday    |                                                                    | no  | Workday — need host/tenant/site |
| IMC Trading    | greenhouse | token=imc                                                          | yes | Verified — quant |
| Optiver        | greenhouse | token=optiverus                                                    | yes | Verified — quant |
| Radix Trading  | custom     |                                                                    | no  | Custom careers site |
| SpaceX         | greenhouse | token=spacex                                                       | yes | Verified |
| D.E. Shaw      | custom     |                                                                    | no  | Custom careers site |
| Five Rings     | greenhouse | token=fiveringsllc                                                 | yes | Verified — quant |
| Neuralink      | greenhouse | token=neuralink                                                    | yes | Verified |
| Cursor         | ashby      | slug=cursor                                                        | yes | Verified — Anysphere |
| Snowflake      | ashby      | slug=snowflake                                                     | yes | Verified (fixed from bad greenhouse token) |
| Akuna Capital  | greenhouse | token=akunacapital                                                 | yes | Verified — quant |
| LinkedIn       | custom     |                                                                    | no  | Microsoft-owned; custom careers site |
| Hugging Face   | custom     |                                                                    | no  | No public ATS API found |
| Disney         | workday    |                                                                    | no  | Workday — need host/tenant/site |
| GitHub         | custom     |                                                                    | no  | Microsoft-owned; custom careers site |
| Bloomberg      | custom     |                                                                    | no  | Custom careers site |
| X (Twitter)    | custom     |                                                                    | no  | Custom careers site |
| Spotify        | lever      | slug=spotify                                                       | yes | Verified |
| Tesla          | custom     |                                                                    | no  | Custom careers site |
| Anduril        | greenhouse | token=andurilindustries                                            | yes | Verified |
| Nextdoor       | greenhouse | token=nextdoor                                                     | yes | Verified |
| Datadog        | greenhouse | token=datadog                                                      | yes | Verified |
| NASA           | custom     |                                                                    | no  | Government — USAJobs.gov |
| ByteDance      | custom     |                                                                    | no  | Custom careers site |
| Twitch         | custom     |                                                                    | no  | Amazon-owned; custom careers site |
| Indeed         | custom     |                                                                    | no  | No public ATS API for main brand |
| Slack          | workday    |                                                                    | no  | Salesforce-owned; Workday — need config |
| Blue Origin    | custom     |                                                                    | no  | No public ATS API found |
| Snap           | custom     |                                                                    | no  | Custom careers site |
| Atlassian      | custom     |                                                                    | no  | Custom careers site |
| Verily         | custom     |                                                                    | no  | Alphabet; no public ATS API found |
| MongoDB        | greenhouse | token=mongodb                                                      | yes | Verified |
| Goldman Sachs  | custom     |                                                                    | no  | Custom careers site |
| Flow Traders   | greenhouse | token=flowtraders                                                  | yes | Verified — quant |
| eBay           | workday    |                                                                    | no  | Workday — need host/tenant/site |
| Oracle         | custom     |                                                                    | no  | Custom careers site |
| Palo Alto Nets | custom     |                                                                    | no  | SmartRecruiters — needs adapter |
| Riot Games     | greenhouse | token=riotgames                                                    | yes | Verified |
| Shopify        | custom     |                                                                    | no  | Custom careers site |
| Splunk         | workday    |                                                                    | no  | Cisco-owned; Workday — need config |
| Blackrock      | custom     |                                                                    | no  | Custom careers site |
| Capital One    | workday    |                                                                    | no  | Workday — need host/tenant/site |
| Duolingo       | greenhouse | token=duolingo                                                     | yes | Verified |
| Morgan Stanley | custom     |                                                                    | no  | Custom careers site |
| Lockheed       | workday    |                                                                    | no  | Workday — need host/tenant/site |
| Red Hat        | workday    |                                                                    | no  | IBM-owned; Workday — need config |
| IBM            | custom     |                                                                    | no  | Custom careers site (cutoff company) |
| Samsung        | greenhouse | token=samsungsemiconductor                                         | yes | Verified — Samsung Semiconductor board |
| Zoom           | custom     |                                                                    | no  | No public ATS API found |
| Cohere         | ashby      | slug=cohere                                                        | yes | Verified |
| Glean          | greenhouse | token=gleanwork                                                    | yes | Verified |
| Box            | greenhouse | token=boxinc                                                       | yes | Verified |
| JPMC           | custom     |                                                                    | no  | Custom careers site |
| Okta           | greenhouse | token=okta                                                         | yes | Verified |
| Rippling       | custom     |                                                                    | no  | No public ATS API found (was bad greenhouse token) |
| Intuit         | workday    | host=intuit.wd1.myworkdayjobs.com;tenant=intuit;site=External      | no  | Workday config returns 401; verify site/tenant |
| Cisco          | workday    | host=cisco.wd5.myworkdayjobs.com;tenant=cisco;site=External_Career_Site | no  | Workday config 404; verify host/site |
| Uber           | workday    | host=uber.wd1.myworkdayjobs.com;tenant=uber;site=External          | no  | Workday config 422; verify site/tenant |
