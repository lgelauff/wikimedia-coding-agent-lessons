---
name: route-vetting
description: >-
  Vet a candidate host or API for addition to the Mandated Services Registry, the list of
  approved routes agents may fetch from directly. Use when someone asks to approve, add,
  whitelist or "make allowed" a source, when a session keeps failing on a host that is not
  yet approved, or when Lodewijk asks for candidate routes and why they are justified. It
  reads the provider's own documentation, terms and robot policy, assigns a verdict
  (supported / conditional / not supported / ask / unverified), and drafts the connector row and
  registry entry for his approval. Use it INSTEAD of adding a host because it "looks like an
  API": the traps are a robots file that is really a bot-challenge page, a documented API
  that only works with a token we do not have, and a host that is approved yet still fails
  because the recipe is wrong. Not for fetching from a source that is already approved: use
  source-connectors for that.
---

# route-vetting: investigate a potential new approved route

An approved route is a host in `agent-tooling/settings/mandated-services.json`, backed by a row in
`skills/source-connectors/references/library.md`. Agents fetch approved hosts directly; anything
else goes through the Internet Archive. Adding a route changes what every agent may do, so the
output of this skill is a **proposal**: Lodewijk decides, typed in the session's own chat.

## What you may fetch while vetting

Standing rule (Lodewijk, 2026-10-16, AGENT-LOG E392/E393): **API documentation, terms/licence
pages, `robots.txt` and robot/bot/crawler-policy pages may be fetched directly on any host**, with
the project User-Agent, about 1 request/s, backing off on 429/5xx. Doc paths that the host's own
robots file disallows go through the Internet Archive instead.

**Never call the API itself or download data while vetting.** That is exactly what approval
would permit; doing it first defeats the review.

## Criteria to weigh

Each criterion gets a line in the proposal. A route needs the first four to pass; the rest
decide the policy attached to it, or tip a borderline case.

| # | Criterion | Question to answer | Passes when | Fails or limits when |
|---|---|---|---|---|
| 1 | **Need** | What concrete work needs it, and how much? | named sessions, projects or queue items, with a count | "might be useful someday" |
| 2 | **Sanctioned door** | Is this an intended route for programs, from the provider or a mirror with its own sanctioned door? | documented API, bulk download or data portal from the provider itself; **or a mirror** with its own sanctioned door: it documents programmatic access itself, carries the content under the same licence, and can be verified against the original (checksums). No endorsement by the original provider is needed; being listed by the provider (e.g. Wikimedia's dump mirrors) is a plus, not a requirement | page crawling, scraper services, reverse-engineered endpoints, mirrors that repackage content without a licence or a way to verify it |
| 3 | **Permission** | Do docs, terms, robot policy and TDM reservations allow automated use? | the docs describe the programmatic use (this wins over a robots.txt disallow, see below) and terms do not forbid it; or, with no docs, robots.txt allows it | terms forbid automated/AI use; a TDM reservation; a token is required that we were not issued; no docs and robots disallows or is unreadable |
| 4 | **No cheaper equivalent** | Does an approved route already give the same thing? | it adds coverage or quality we lack (count it) | an approved route already covers it (Unpaywall vs OpenAlex locations) |
| 5 | **Load and manners** | Can our expected volume stay well inside the documented limits? | documented limit known; our volume is a small fraction; responses cacheable | no stated limit and heavy volume; bursty jobs; no caching possible |
| 6 | **Access and identity** | What key, account, registration or identifying header is requested, and who provides it? | none; or registration encouraged/required, which Lodewijk does (his task) and the key goes into the agent-secrets store | agents would need to create accounts, accept terms, share personal credentials, or send his e-mail without his yes |
| 7 | **Data class** | Personal data? Licence? May results be republished, or sent to a third-party model host? | open licence, no personal data | personal data (policy: counts and links only); restrictive or per-record licences; analysis-only data |
| 8 | **Legal context** | Jurisdiction, TDM rules, database rights, public-sector reuse law | clear reuse basis (open licence, public-sector reuse act) | TDM reserved; database right asserted; unclear terms: CONDITIONAL at most |
| 9 | **Scope** | What is the narrowest host and path set that meets the need? | exact hosts, named paths | broad suffixes (`*.example.org`) without a reason for each subdomain |
| 10 | **Stability** | Versioned, maintained, with deprecation notices? Fallback if it disappears? | stable versioned API; a fallback named (often the Internet Archive) | undocumented or beta endpoints that change silently |
| 11 | **Downside if wrong** | What happens if agents misuse it? | worst case is a throttled request | IP blacklisting of the user's address, account bans, legal letters: needs a stricter policy or a no |
| 12 | **Evidence quality** | How do we know each fact above? | read live in the provider's docs today, cited with date | from memory or a third-party blog: [guess] until confirmed |

**Registration, accounts and identifying headers (Lodewijk, 2026-10-16).** If a provider
*encourages* registration (an API key, a client, an account), we register: that is
**Lodewijk's task**, never an agent's. Record it as "registration encouraged: Lodewijk registers
(pending)" in the connector row and on his to-do list; use the route anonymously only where the
docs allow that in the meantime. The same applies when a provider asks for an identifying header
or parameter (an e-mail in `User-Agent`, `mailto=`, `email=`, `tool=`): his e-mail address goes
out only with his yes, so flag it rather than filling it in. A route with none of these
requirements can go straight onto the list of routes to create; its exact shape (hosts, paths,
limits, policy) is still decided per route.

**Scope of the three rules below.** They are for *judging candidates* when Lodewijk has asked
for new routes to be investigated. They decide what verdict to propose; they do not by
themselves permit fetching data from any host. Only a registry entry that Lodewijk approved does.

**Documented use wins over robots.txt (Lodewijk, 2026-10-16).** If the provider's own docs
describe programmatic access to an endpoint, assume that use is OK, even when robots.txt
disallows the same path: robots.txt governs crawlers, while the docs are the provider's explicit
invitation (NCBI E-utilities, Zenodo's `/api`, KOOP's SRU all document APIs that their robots
files disallow). Stay strictly inside what the docs describe: their endpoints, parameters,
rate limits and auth. This does not override terms that forbid automated or AI use, a TDM
reservation, or a required token we were not issued.

**Grey cases go to Lodewijk (2026-10-16).** Reject a route only when it is **explicitly
disapproved in public**: terms that forbid automated or AI use, a robots.txt disallow with no
documented API, named AI-crawler bans, a TDM reservation. Anything not explicitly disapproved and
not clearly supported (no docs, silent terms, unreadable robots, an unclear mirror) is not a
silent no: bring it to Lodewijk as **ASK** with the evidence you have, and he decides.

**Aggregators and archives (Lodewijk, 2026-10-16).** A service whose purpose is to collect and
redistribute other sources (the Internet Archive, IA Scholar/fatcat, CORE, OpenAlex-style indexes)
is presumed OK as a door: criteria 2 and 3 are judged on the aggregator's own docs, terms and
robots, not re-checked for every original source behind it. The other criteria still apply,
especially load (5: their limits are shared by everyone) and data class (7: personal data in the
content stays personal data). For everything else, "it depends": run the full table.

## Steps

1. **Name the need.** Which session, project or failed item needs this host, and how many items
   it unlocks. "Might be useful" is not a need; a count from a queue or log is.
2. **Check it is not already covered.** `python3 agent-tooling/scripts/mandated_services.py
   --emit-hosts`. An approved host that still fails is a recipe problem, not a missing route
   (Phabricator failed 5 vault items while approved, 2026-10-16).
3. **Read robots.txt, then believe only real robots files.** A `robots.txt` that comes back as
   HTML, or with HTTP 202, is a bot-challenge page, not a policy (EUR-Lex, 2026-10-15): treat the
   site's pages as closed to scripts and look for a separate API host. Status codes: a 404 means
   no robots file (no restrictions), but 401/403/429, a 5xx or an unreachable host means **do
   not approve yet**: record UNVERIFIED and retry another day. Honour any `Crawl-delay`, and save
   the file's text, fetch date and status in the log, since the file can change later.
4. **Check machine-readable mining opt-outs.** Look for `/.well-known/tdmrep.json`, a `tdm-reservation`
   header or meta tag, and `ai.txt`. A text-and-data-mining reservation is legally meaningful in
   the EU even when robots.txt allows crawling: it makes the verdict CONDITIONAL at most (metadata
   lookups, no mining of the content). `llms.txt` is not a permission file; ignore it for vetting.
5. **Read the documentation and the terms, separately.** Docs: is programmatic or bulk access
   invited (quote the sentence, under 15 words); auth (none / free key / registration /
   institutional); documented rate or fair-use limits. Terms of service: any clause on automated
   access, AI or text mining, and the content licence. A permissive robots file does not override
   terms that forbid automated use, and vice versa; both must allow it.
6. **Read the robot or bot policy page** if one exists (Wikimedia's Robot policy: concurrency 1,
   at least 1 s apart, pause on 5xx). It overrides a generic "about 1 request/s".
7. **Note personal data.** If responses carry names, e-mail addresses or free text by people,
   the policy must say "counts and links only, never republish", as for mailing-list archives.
8. **Assign a verdict.**
   - **SUPPORTED**: docs describe the programmatic use; terms do not forbid it.
   - **CONDITIONAL**: needs a key, a guestbook or click-through, per-dataset terms, or a narrower
     path. Keys are registered by Lodewijk, never by an agent.
   - **NOT SUPPORTED**: only when explicitly disapproved in public: terms forbid automated or AI
     use; a robots disallow with no documented API; named AI-crawler bans (Munich CONSUL,
     2026-10-12, including a script a human runs for us); a TDM reservation; a documented API
     that requires a token we have not been issued.
   - **ASK**: not explicitly disapproved and not clearly supported (no docs, silent terms, an
     unclear mirror). Bring it to Lodewijk with the evidence; he decides.
   - **UNVERIFIED**: the docs or robots could not be read yet (outage, challenge page). Say why
     and retry; if it stays unreadable, it becomes ASK.
9. **Draft, do not land.** For SUPPORTED or CONDITIONAL, draft the library row (endpoint host in
   the endpoint cell, so the drift guard sees it) and the registry entry, then run
   `python3 agent-tooling/scripts/mandated_services.py`. It must report the new host as drift
   before the registry entry and `OK` after. Show both to Lodewijk; commit only after his yes.
10. **Record** the verdict and evidence in AGENT-LOG: doc URLs, fetch dates (or Wayback capture
    timestamps), the robots text and status, the quote, and the verdict.

## Sources for these practices
Checked 2026-10-16: RFC 9309 (Robots Exclusion Protocol; rules are not access authorisation);
Google's documented robots.txt status-code handling; IETF draft-farzdusa-webbot-datacollection
(document robots checks; Crawl-delay); Chicago Booth and UT Libraries scraping guides (API first,
terms and robots are separate questions); IPTC Generative AI Opt-Out Best Practices (2025) and the
TDMRep specification (machine-readable TDM reservations).

## Output for Lodewijk (one table)

| Route | Resource | Need (count) | Verdict | Auth | Documented limit | Licence | Proposed policy | Source + date |

Label every fact [confirmed] (read in the docs, cite it) / [concluded] / [guess]. Facts about an
API written from memory stay [guess] until a doc page confirms them.
