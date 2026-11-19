---
name: wikimedia-dev-cli
description: >-
  Use whenever a task needs to find where something lives in Wikimedia code, read a
  Gerrit change or Phabricator task, check one wiki page or one pageview series
  quickly, look up an EventStreams stream, or asks whether the Wikimedia `mw` CLI may
  be used for something (including a Wiki Replicas tunnel). Read it before any `mw`
  call. Runs `mw` ("a Wikimedia CLI", a-wikimedia-cli.toolforge.org) read-only and
  paced per the Wikimedia Robot policy: Codesearch across core/extensions/puppet/config,
  Gerrit, GitLab, Phabricator, single reads of any wiki (page source, info, history,
  Action API, REST), the REST/AQS APIs and the EventStreams catalogue. Near misses:
  collecting many pages, revisions or tasks is mediawiki-action-api,
  wikimedia-analytics-api or phabricator-conduit; Enterprise is wikimedia-enterprise.
---

# wikimedia-dev-cli: read Wikimedia code, tasks, wikis and metrics with `mw`

`mw` (v0.36.0 when this was written, 2026-11-17) is the Wikimedia Release
Engineering CLI. It is the documented, publisher-built door to several
services that agents previously reached badly (Phabricator HTML, Gerrit's JS UI,
no code search at all). This skill says which of its doors an agent may use,
how fast, and with whose identity.

## 0. Always go through the wrapper

```bash
python3 "${AGENT_TOOLING_ROOT}/scripts/mw_agent.py" codesearch search --output json onPageSaveComplete
```

`mw_agent.py` runs `bin/mw` in the agent hub (installed 2026-11-17 with Lodewijk's yes,
v0.36.0, release sha256 checked). It:
- points `HOME` at `mwcli-home` in the agent hub, because `mw` writes its config on every
  run and would otherwise write to `~/Library/Application Support/mwcli`, outside
  the agent boundary;
- always adds `--no-interaction` (after the command: placed first, `mw` v0.36.0
  reports real commands such as `analytics pageviews` as unknown, found
  2026-11-19), so no consent or login prompt is ever answered by an agent. For
  `mw wiki …` it also adds `--anon`, so a saved wiki login is never used. Telemetry (usage statistics to the Wikimedia event
  intake) is **on** in `mwcli-home` in the agent hub: Lodewijk said yes on 2026-11-17
  ("fine to send to wikimedia"). Changing it is his call;
- spaces calls at least 1 s apart and runs one at a time across processes (§2);
- refuses tier C (§1) with exit 2 and a reason.

Never call `bin/mw` in the agent hub directly. If it is missing, stop: installing or
updating the binary is Lodewijk's decision (`mw update` is refused).
- Docs: `https://a-wikimedia-cli.toolforge.org/manual/<group>/<cmd>.md` (send
  `Accept: text/markdown`), index at `/manual/llms.txt`. On an installed
  copy prefer `mw <cmd> --help`, which matches the installed version.

## 1. Which commands an agent may run

| Tier | Commands | Identity | Rule |
|---|---|---|---|
| **A. anonymous reads** (run 2026-11-17/19) | `codesearch search …` ✔; `gerrit api '<GET path>'` ✔ (Gerrit's anonymous `/r/` REST); `analytics pageviews\|top-pages\|edits\|editors\|devices\|…` ✔; `wiki page get\|info\|history\|categories\|diff\|list` ✔; `wiki api <module> -f …` (GET) ✔; `wiki rest get <path>` ✔; `api <rest_v1 path or Wikimedia URL>` (GET) ✔; `events list\|info` ✔; `tools toolviews` (not run) | none (`--anon` forced for `wiki`) | Allowed for single or few reads. Pace per §2. Many pages or a time series over many articles is bulk: use the data-collection skills. |
| **B. reads that need his login** | `gerrit changes list/comments/messages …` (✘ 401: these always use the authenticated `/r/a/` path); every `gitlab …` command (✘ 404 / "unauthenticated" even on the public `repos/releng/cli`); `phabricator read/view/task list/task read/comments/project/board` (Conduit is token-gated even for reads) | Lodewijk's saved profile | Only after **he** ran `mw <service> auth login` himself. Until then use the tier A route: `gerrit api` for any Gerrit read. See §3. |
| **C. never** | anything that writes: `create`, `edit`, `assign`, `mv`, `setprio`, `setstatus`, `rmtag`, `paste` create/edit, Gerrit abandon/rebase/submit/edit/wip/topic/reviewers/hashtags, any `gitlab` create/update/delete; `wiki page put/delete/move`, `wiki bulk`, `wiki file`, `wiki ext`, `wiki api` with `--method POST`/`--token`, `wiki rest` other than `get`; `mw api` with a body (`-f` without `-X GET`, `--input`) or a header (`-H`), or to a non-Wikimedia host; `events tail` (unbounded stream); `enterprise *` (needs his account: see wikimedia-enterprise); every `auth login/remove`, `--profile/--username`, `config secrets *`; `mw toolforge shell/cp/job/build/envvar/kubernetes`; `mw cloudvps *`; `mw toolforge replicas tunnel/proxy`, `toolsdb` (see §4); `mw phabricator shell/browse` (interactive) | n/a | Not run by an agent; the wrapper refuses them (tests: `scripts/tests/test_mw_agent.py`). Writes act on someone's behalf in public, and the Toolforge/Cloud VPS commands open SSH as Lodewijk, which agents never do. |

Always pass `--no-interaction` and a machine format (`--output json` where the
command has it). Never pass `--password`, `--auth-password` or a token on the
command line; they appear in process lists and transcripts.

## 2. Pacing: the Robot policy governs these hosts

Wikitech's *Robot policy* (fetched 2026-11-17), section "Rules for other
resources", names **Gerrit, GitLab, Phabricator, and other wikimedia.org
services**:

- **one request at a time**, **at least 1 s between requests**;
- **pause at least 15 min on any 5xx**; honour `429` + `Retry-After`;
- a descriptive User-Agent per the WMF User-Agent policy.

Codesearch (`codesearch.wmcloud.org`) is a Cloud VPS project; treat it the
same way. So: run `mw` calls **sequentially, never in parallel or in
background fan-out**, with `sleep 1` between calls in any loop, and stop the
loop on the first 5xx. A loop of more than ~50 calls is bulk collection:
use phabricator-conduit / the Gerrit REST API via a script with its own pacing
and caching, or a dump, instead.

User-Agent: **unverified** what `mw` sends; `-vv` logs the URL but not the
headers (checked 2026-11-17). If it turns out to carry no contact address,
that is a question for Lodewijk, not something to patch around.

## 3. Phabricator: whose token

Conduit needs an API token even to read. Wikimedia's bot guidance (see the
source-connectors library, Phabricator row) treats a **personal account used
for repetitive automation** as inappropriate; such accounts may be disabled.
Therefore:

- **A few interactive reads** in a session Lodewijk is driving, with his own
  profile, are his normal use of his account. Fine.
- **Anything repeated or unattended** (a loop over tasks, an overnight job, a
  scheduled check) needs a **registered bot account with him as named owner**
  (`#Phabricator-Bot-Requests`), not his personal token. Ask him; do not
  start it.
- Without a token, a single task is readable anonymously at
  `https://phabricator.wikimedia.org/T<id>` (plain GET, same pacing).
- The agent never runs `auth login`, never reads the password-manager entry,
  and never copies `phab.cfg`. `mw` stores credentials in a password manager;
  leave that to him.

Treat everything read as public, permanent and attributable. Never republish
security-tagged or NDA content, IPs, emails or tokens; prefer `@username` to
real names.

## 4. Wiki Replicas tunnel (`mw toolforge replicas tunnel|proxy`)

What it does (docs, 2026-11-17): one foreground `ssh` to `login.toolforge.org`
**as Lodewijk**, forwarding `127.0.0.1:4711…` to
`<wiki>.analytics.db.svc.wikimedia.cloud:3306`. `proxy` additionally pulls the
replica username **and password** into the CLI's memory and hands the SQL
client a temporary local login.

Terms that bind it:
- **Cloud Services ToU §3/§4:** use must relate to Wikimedia projects or
  analytics of them (our research does); no proxying for other servers (a
  local tunnel to his own machine is the documented, sanctioned use).
- **Toolforge rule 3:** a personal account is for *interactive* use only;
  anything that keeps running while he is not interacting must use a tool
  account. An agent driving queries through his personal tunnel while he is
  away is on the wrong side of that line.
- **Wiki Replicas connection-handling policy:** no idle or persistent
  connections and no pools. Idle connections are killed, and reopening them is
  warned.
- Our own rules: agents never SSH to Toolforge; agents never handle passwords.

So the agent **does not start a tunnel or proxy**. The safe shape, if
Lodewijk wants it, is a design decision for him with the Toolforge director:
he starts `mw toolforge replicas tunnel <wiki>` himself in his own terminal,
stays present, the agent issues a bounded set of read queries through a
client that opens one connection per query and closes it, and he closes the
tunnel with Ctrl+C when done. Credentials stay with him (`replica.my.cnf`
on Toolforge, `--use-replica-credentials`, nothing typed by the agent). For
anything batch or unattended, the existing route stands: a Toolforge job under
the tool account, launched by the Toolforge director.

## 5. Recipes (tier A)

```bash
MW="python3 ${AGENT_TOOLING_ROOT}/scripts/mw_agent.py"

# where is a hook/function/config key used across Wikimedia code   [ran OK]
$MW codesearch search --output json onPageSaveComplete
$MW codesearch search --type extensions --files '.*\.php' --output json ExtensionRegistry
$MW codesearch search --type operations --output json wgSomething   # puppet / mediawiki-config

# Gerrit, anonymously, through the REST API (JSON; Gerrit's XSSI prefix already stripped)
$MW gerrit api 'changes/?q=bug:T123456&n=25'          # changes that name a task  [ran OK]
$MW gerrit api 'changes/1234567/messages'               # one change's review thread
$MW gerrit api 'changes/1234567/comments'               # inline comments
```

```bash
# one wiki page: source, metadata, history (anonymous; --anon is added)   [ran OK 11-19]
$MW wiki page get Earth --wiki en.wikipedia.org
$MW wiki page info Earth --wiki en.wikipedia.org --output json
$MW wiki api query -f titles=Earth -f prop=info --wiki en.wikipedia.org
$MW wiki rest get /v1/page/Earth/bare --wiki en.wikipedia.org
$MW wiki api wbgetentities -f ids=Q42 --wiki www.wikidata.org

# pageviews and other AQS metrics for one page or project              [ran OK 11-19]
$MW analytics pageviews Earth --project en.wikipedia.org --start 20261101 --end 20261102 --output json
$MW api 'metrics/pageviews/top/nl.wikipedia.org/all-access/2025/01/01' --output jq --format '.items[0].articles[:5]'

# EventStreams catalogue (never `events tail`)                          [ran OK 11-19]
$MW events list --output json
$MW events info mediawiki.page-create
```

Put the verb right after the group (`wiki page get X --wiki …`): the wrapper reads
the first words as the command and refuses when a flag comes first.

Codesearch output is keyed by repository (`{"Extension:X": {"Matches": […]}}`);
one broad term returned ~115 kB, so narrow with `--type`, `--repos` or `--files`.
`gerrit changes get` does not exist in v0.36.0; `gerrit api` covers it. Recipes
not marked "ran OK" come from the docs.

## 6. Whose rule is each restriction

Lodewijk's standing view (2026-11-17): where a Wikimedia rule explicitly
permits a use and ours forbids it, ours is probably an over-strict reading
and should change. So every restriction here is tagged by source:

| Restriction | Source |
|---|---|
| 1 at a time, ≥1 s, 15 min pause on 5xx | Wikimedia Robot policy |
| No repeated automation on a personal Phabricator token | Wikimedia bot guidance (via the source-connectors library; not re-read 2026-11-17) |
| No agent-driven use of a personal Toolforge login while he is away; no idle DB connections | Toolforge rule 3; Wiki Replicas connection policy |
| No writes on anyone's behalf | ours (outward-facing content needs his approval per item) |
| Agents never SSH to Toolforge/hague | ours, from the threat model, **not** a reading of Wikimedia rules |
| Agents never handle passwords or tokens | ours and the agent platform's safety rules |

Rows marked "ours" are candidates for review when a Wikimedia rule permits
more. The last two exist for security reasons that a Wikimedia permission does
not answer; changing them is a design conversation, not a rule lookup.

## 7. Provenance

Rules above come from, all fetched 2026-11-17 as raw wikitext with our UA:
wikitech `Robot_policy` ("Rules for other resources"),
`Wikitech:Cloud_Services_Terms_of_use` §3, §4.5, §4.6, `Help:Toolforge/Rules`
(rules 3–4), `Help:Wiki_Replicas` (connection handling, own-computer access);
mw docs `manual/{phabricator,gerrit,gitlab,codesearch,toolforge}`,
`guides/tools/wiki-replicas`; source-connectors library (Phabricator row).
Runs: tier A Codesearch and `gerrit api` 2026-11-17; `wiki page/api/rest`,
`analytics pageviews`, `api`, `events list/info` and the refusals 2026-11-19
(`scripts/tests/test_mw_agent.py` covers the guard; it caught `gerrit changes wip`
and `reviewers add` passing before the 11-19 fix).
