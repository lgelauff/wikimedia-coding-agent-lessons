---
name: route-vetting
description: >-
  Vet a candidate host or API for addition to the Mandated Services Registry, the list of
  approved routes agents may fetch from directly. Use when someone asks to approve, add,
  whitelist or "make allowed" a source, when a session keeps failing on a host that is not
  yet approved, or when Lodewijk asks for candidate routes and why they are justified. It
  reads the provider's own documentation, terms and robot policy, assigns a verdict
  (supported / conditional / not supported / unverified), and drafts the connector row and
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
   - **SUPPORTED**: docs invite programmatic use; robots and terms do not forbid it.
   - **CONDITIONAL**: needs a key, a guestbook or click-through, per-dataset terms, or a narrower
     path. Keys are registered by Lodewijk, never by an agent.
   - **NOT SUPPORTED**: docs, terms or robots forbid it. A disallow-all plus named AI crawlers
     means no automated access, including a script a human runs for us (Munich CONSUL, 2026-10-12).
     A documented API that requires a token we have not been issued is also no access.
   - **UNVERIFIED**: the docs could not be read. Say why.
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
