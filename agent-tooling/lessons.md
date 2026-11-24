# Benchmark-design lessons

Hard-won from building and running LLM benchmarks in `scripts/` and
`playbooks/`. Every one of these was paid for with a wrong number that looked
right. Results live in [`feedback/liftwing.md`](feedback/liftwing.md).

---

## 1. Compute the trivial baseline BEFORE you read any result

The single most expensive omission. A `segment_type` classification scored
**58.3% value-accuracy with 100% schema compliance** and read as a pass. Then
the majority-class baseline turned out to be **70.7%** — "always answer `rule`"
beat the model outright.

The report had no baseline column, so the number looked like a grade. It was a
loss.

**Rule:** a metric without its baseline printed beside it is not a result, it is
a number. Compute majority-class, regex/heuristic, and (where relevant) an
*oracle-tuned* baseline — thresholds fitted on the test set itself. A generous
baseline is the honest one: if the model cannot beat a baseline that cheated,
it cannot beat it.

## 2. Accuracy hides label collapse; report macro-F1 alongside it

A model scored 37.9% accuracy on a 3-way task **while never once emitting one of
the three labels**. Accuracy cannot see that. Macro-F1 penalises it directly,
because a never-predicted class contributes an F1 of 0.

**Rule:** report macro-F1 (primary) *and* accuracy, per-class recall, and a
`labels used N/M` line. The **gap** between accuracy and macro-F1 is the
frequency-bias diagnostic.

## 3. Stress-test the catch-all class before you run

Defining a middle class as "related or overlapping" made it the safe answer and
the model chose it 21/29 times. The same pathology recurred at scale: loose
classes act as sinks (`principle` P=0.14 R=0.91, `procedure` P=0.26 R=1.00)
while the largest class starves (`obligation` R=0.13).

**Rule:** for every label set, ask *"is there a class a lazy model can always
pick?"* If yes, either tighten its definition or expect it to absorb everything.

## 4. Schema-validity and value-accuracy are different metrics

676 JSON calls returned **100% schema-valid** output whose **values lost to
always-answering-the-majority-class**. Perfect form, useless content. A pipeline
gating on "did it parse?" would have shipped garbage at scale and never known.

**Rule:** never let structural validity stand in for correctness. Score them
separately, always, and say so in the report.

## 5. Your null control can contain the very bug you are testing for

The worst one. A code-review benchmark built "functionally identical by
construction" null diffs by renaming an identifier — but renamed only on `+`/`-`
lines, leaving context lines untouched. A parameter declared on a context line
kept its old name while the body referenced the new one: **an undefined
variable, a genuine severe defect, inside the control that was supposed to
contain none.**

A model correctly reported it. The benchmark would have scored that as an
*invented issue* — **penalising the model for being right**, and systematically
favouring whichever model noticed least.

Caught only because a verdict was read by hand instead of trusted as a number.

**Rule:** a control is a claim about ground truth and needs verifying like any
other. Assert the invariant mechanically (here: no orphaned original identifier
survives anywhere in the diff) and spot-read raw outputs before trusting a
score. And prefer transformations that are *provably* safe — this rename is only
safe when every occurrence in the whole file at that revision is inside the
hunk being rewritten.

## 6. Check the independence assumption before importing an ensemble result

Published work says agreement-based ensembles of small models can beat a single
large one. Applied to `qwen3-14b` + `qwen36-27b` it **failed**: agreement-gated
accuracy 63.8% at 73.7% coverage, against **64.3% from the 27B alone at full
coverage**. Discard a quarter of the data, get worse answers.

Cause: same family, same training data, same failure modes. When they agree they
are frequently **both wrong**. Agreement was a shared prior, not independent
evidence. The published result concerned ensembles of *different* models.

**Rule:** an ensemble finding carries an independence precondition. Check it.
And when measuring agreement between raters, use raters from different families
or the number means nothing.

## 7. Agreement needs a ceiling or it is uninterpretable

For tasks with no ground truth (review, critique, judgement), agreement with a
stronger model is the honest measure — but a bare kappa cannot be read. If two
reference models agree with *each other* at kappa 0.40, a subject at 0.35 is as
good as any rater and the task is simply subjective.

**Rule:** always compute reference-vs-reference agreement first and report every
subject score as a fraction of it. Most agreement studies omit this, which is
how "the small model is bad" gets published when the truth is "nobody agrees."

**And keep the claims apart:** high agreement means **substitutable**, never
**correct**. Two models can be confidently wrong together — see lesson 6.

## 8. Pre-register the threshold, or the eval is decoration

Straight from an adversarial LLM review of our own design
(`wikipedia-policy-change/.claude/policy_network_review2_llm.md` §1.2):

> *"Without a pre-registered threshold the eval is decoration — you will run it,
> get some number, and rationalize whichever number you get."*

Fix the pass mark, the baseline, the asymmetric error, and `n` (with its CI)
*before* the first call. Template:
[`feedback/liftwing-bench-npov-prereg.md`](feedback/liftwing-bench-npov-prereg.md).

## 9. Name the asymmetric error and give it its own metric

Aggregate accuracy hides the error that actually costs you. A false merge hides
a policy reform; a false negative in triage silently drops a candidate; a
hallucinated quote enters the corpus as a rule nobody wrote.

**Rule:** each task names its dangerous direction and scores it separately with
its own pass mark. `governance_class` beat every baseline and still **failed**
on `user-admin` recall 0.672 vs a 0.70 gate — the right outcome.

## 10. Do the zero-call analysis first

The ensemble result in lesson 6 was killed by re-analysing output already on
disk — no new calls, a few minutes, before any engineering was spent building
the pipeline it would have justified.

**Rule:** before running anything new, ask what the data you already have can
refute.

## 11. A regression canary confirms the verdict, not the failure mode

A known-failing task was kept in the suite so that a sudden pass would signal a
harness bug. It worked — both models failed it again, independently, which is
what validated the harness.

But the *mechanism* did not reproduce: the earlier run showed zero predictions
of one label, the later run used all three labels with terrible recall on one.
Same conclusion, different pathology, driven by a prompt change.

**Rule:** canary on the verdict. Do not assume the failure mode is stable — it
is prompt-sensitive even when the conclusion is not.

## A background wait whose condition can never match looks identical to work in progress

`until grep -q "DONE" job.log; do sleep 30; done` is a normal way for an agent to wait on a long job.
Its failure mode is that **a wrong pattern does not error — it waits forever**, and the harness
correctly reports the task as *running*. Nothing distinguishes "still working" from "will never
finish" without inspecting the process.

Observed: a watcher matching `'deposit complete|DONE|Error|Traceback|error'` ran for **24 hours** on a
job that had finished in 276 seconds, because the script's actual last lines were
`✅ 58 files verified present …` and `NEXT: registry row …` — none of the guessed tokens.

Two habits that prevent it:

- **Derive the sentinel from the program, not from a guess.** Run it once, read the final line, and
  match that. If you cannot run it first, match on something structural you control — the process
  exiting, or a file the job writes last — rather than on wording.
- **When auditing your own background work, search for the waits, not just the jobs.** `pgrep` for the
  script names finds the work; it does not find the shell you left watching for it. The watcher
  outlives the job by definition.
- **`until ! pgrep -f "<pattern>"; do sleep 20; done` never terminates when run through an agent
  shell.** The harness wraps the loop in `zsh -c '… eval "until ! pgrep -f \"<pattern>\" …"'`, so the
  pattern appears in the watcher's *own* command line, and `pgrep -f` always finds the watcher itself.
  Six such loops kept polling for 13+ hours after their job had finished (2026-09-21), and showed in
  the task list as live work. Wait on something the watcher cannot match: `while kill -0 <pid>` on
  the job's PID captured at launch, or a sentinel file the job writes last. If `pgrep` is unavoidable,
  make the pattern unmatchable by its own text, e.g. `pgrep -f "[s]ection_labels_multiwiki"`.


## Unordered set iteration makes an analysis nondeterministic, and a seed does not save you

Re-running an 80-stage pipeline against committed outputs: ~190 files reproduced byte-identical,
6 did not. Two traced to one cause — Python randomises string hashing per process, so
`for x in set(...)` yields a different order each run. One case only reordered a printed list;
the other picked a different representative file per article (`cand = [f for f in units.get(art, ())]; bf = cand[0]`),
which shifted the analysis population by 3 articles and moved a published-adjacent result in the
third decimal. A third case left every point estimate identical and moved only the bootstrap
CIs: the script *was* seeded, but the resample drew against differently ordered arrays
[confirmed on all three, 2026-09-23; 9 unsorted `for ... in set(` loops in that repo by grep, so
the blast radius is concluded, not measured].

- **Sort at every point where order can leak into a result**: building an array, drawing a
  sample, or any "pick one" decision. A seeded RNG only protects you if what it draws against is
  stable.
- **Make byte-identical re-runs a first-class check** in any analysis pipeline. Self-tests pass
  happily while the numbers move; only re-running and diffing the artifacts sees it.

## A checksum manifest for another host must be built from the real directory entries

Verifying a laptop→server copy with `sha256sum -c`: all 18 accented filenames failed although
the bytes were identical. The manifest's paths were Unicode-NFC (taken from a tool's output)
while the macOS directory entries are NFD. APFS matches either form; Linux ext4 does not
[confirmed, 2026-09-22]. Build any `.sum` destined for another host from the filesystem itself
(`find -print0 | xargs -0 shasum`), and verify it once on the target before trusting it.

## A directory created by scp can have an ACL mask that blocks what the ACL grants

A packet was scp'd from the Mac into the server's one-way exchange folder, and the receiving
user could not read any file in it [confirmed, 2026-09-24, hague]. `getfacl` showed
`user:agent:r-x`, inherited from the parent's default ACL. But scp had created the new
subdirectory with an ACL **mask** of `r--`, and the mask caps every named entry, so the
effective permission lost `x` and the receiver could not traverse into it. The symptom was
"Permission denied" on files the ACL visibly granted, and that misleads: the grant looks right,
and only `getfacl`'s `#effective:` column shows the cause. Fixed with
`setfacl -m u:agent:rx,m:rx <dir>`.

**Rules:** senders copy files into a directory that **already exists** on the receiving side
(created there, so the default ACL applies intact), never let scp or rsync create it. Or the
receiver resets the mask after arrival. When an ACL grant "doesn't work", read the
`#effective:` column before anything else.

## A remote job packet's preflight must check every file the launch runs, not a proxy

Toolforge, 2026-09-24 [confirmed]. The runbook's preflight grepped the **scanner** for the new
mode's flag. It printed 12 and passed, but the launch goes through a **lane script** that had no
such mode, so a full launch would have rerun the old mode into the old output directory. There,
its `.done` files would have made unprocessed parts look finished. The same session's audit then
found that the scanner imports a helper module the upload step never listed. It existed remotely
only because an earlier run had put it there, so a packet rebuilt from scratch would fail at
import.

**Rules:**
- **Derive the upload list from what actually runs:** the entry point the launch line invokes,
  plus its import closure. Never from memory of "the files I changed".
- **Preflight each file in that list,** at the version the launch needs (a content marker or a
  hash). A check on one file says nothing about its neighbours.
- **A new mode writes to a new output directory.** Resumable jobs treat existing done-markers as
  truth, so a mistaken launch into an old directory silently corrupts it rather than failing.
- **Pin any helper whose version changes the output** (record its hash in the runbook), and
  never upgrade it partway through a corpus.

## Remote jobs: done means evidence, launched means committed, uploaded means verified

Reported by the drop director, 2026-09-24/25 [confirmed].
- **"Done" requires pasted evidence.** A Toolforge job was recorded as finished on a verbal
  report; its results had not actually been retrieved. A job is done only when its end line or
  output count has been pasted into the record.
- **"Running" requires pasted evidence too.** Twice (2026-09-24 and 2026-09-30, reported by the
  drop project's director) a launch was recorded as RUNNING from the command block handed to the
  user, not from what the cluster showed. The job had never started; the second time it cost a
  night. A job is RUNNING only when a pasted `toolforge jobs list` (or the scheduler's equivalent)
  shows it.
- **Launch only committed code.** A job expected to run 10+ hours was started from uncommitted
  local code, so no commit identifies what ran. Commit the exact uploaded bytes before or at
  launch, and record the commit.
- **Upload from a checkout verified at `origin/main`.** The main checkout was 20 commits behind
  origin, and a runbook was about to upload from it, which would have shipped a stale lane
  script. Before any upload, fetch and confirm HEAD equals `origin/main` (or the intended
  commit), and have the preflight print the uploaded files' sha256.
- **Identify sessions by full id, not by name.** A session's name carries over a handover; its
  session id does not. One session spliced two ids together and "proved" they matched. Compare
  full ids, and record them in the agent log.

## macOS `tar` smuggles AppleDouble `._*` files into a Linux copy

Copying a folder from the Mac to the server with `tar -cf - … | ssh host 'tar -xf -'`
[confirmed, 2026-09-26] produced a `._<name>` twin for most files, and GNU tar warned about
unknown `LIBARCHIVE.xattr.com.apple.*` headers (quarantine, provenance, Finder info). macOS
`bsdtar` stores resource forks and extended attributes as AppleDouble entries, and Linux
extracts them as ordinary junk files. A checksum list built on the Mac does not include them,
so the verification passes and the junk stays behind.

**Rule:** on the Mac, run `COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs -cf - …`.
If junk has already landed, remove it on the target with a `find … -name '._*' -type f -delete`
limited to the copied folders.

## A mutation run can be fooled by Python's bytecode cache

Three agents independently hit this on 2026-09-26 [confirmed from their reports]. A mutant that
**survived** turned out to have never run: the previous mutant, of equal size and written in the
same second, left a cached `.pyc`. Python judges a `.pyc` valid by the source's **size and
whole-second mtime**, so it reused that stale bytecode and the tests ran against the wrong code. A
survivor reads as "the tests have a gap", and a false catch as "this guard works", so the error
can go either way.

**Rule:** run every mutant with the cache off or isolated: `python3 -B`, or
`PYTHONDONTWRITEBYTECODE=1` plus `PYTHONPYCACHEPREFIX=<fresh temp dir>` per mutant. Count a mutant as
caught only when a *named test* fails, never on an import or syntax error.

## A privilege split protects you only if the privileged account declines work it could do

The server's admin session (the `ubuntu` user: passwordless sudo and docker-group membership,
root-equivalent) offered to run another session's job itself via `sudo -u agent`. That meant
executing a 15 KB script from a packet it had not read. Lodewijk stopped it [confirmed,
2026-09-24]. Nothing technical would have stopped it: the boundary held because a human was
watching.

**Rule:** the privileged session does not run project code. It inspects, installs and
administers. Analysis, builds, tests and any script from a repo, a packet or another session
run in an unprivileged session, which reads the code first. Moving data in and verifying
checksums is fine; executing is not. On any host, the account that *can* do everything is
exactly the one that must refuse the work an unprivileged account could do instead.

## A service an agent must reason about needs an unauthenticated build identifier

Determining which branch was live on a deployment was not answerable in-band: the branch lives
in the cloud pipeline's source stage, the deployed app exposes no version marker, the platform's
deployment API had no records, and the relevant CLI was not installed. The agent could only hand
the human commands to run elsewhere [confirmed, 2026-09-23]. Expose a build id (commit SHA plus
build time) on an unauthenticated endpoint; "what is actually running" then stops requiring
console access, for agents and humans alike.

Corollary, from the other direction (2026-09-23, wiki-polis e2e on hague) [confirmed]: a
version gate that greps the SERVED HTML for a commit string breaks the day the app becomes an
SPA shell — the page renders nothing to grep and the gate reports "no version" rather than
failing loudly. Read the identifier from the API (`GET /api/v1/session` → `data.gitVersion`) or
the startup log. Assert against a machine-readable surface, never against rendered markup.

## A tool that works in your login shell is absent in the scripts that need it

`dev.sh` assumed `npm` on PATH. Node had been installed per-user under
`~/.local/node-v24/bin` with the PATH line in `~/.profile`, which non-interactive and
non-login shells never read, so the script failed for the agent while `node -v` worked fine
when a human checked [confirmed, 2026-09-22/23]. Either export the PATH where the script will
actually see it (a wrapper, the service unit, or an absolute interpreter path in the script) or
install the runtime somewhere already on the default PATH. "It works when I log in and try it"
does not test what an unattended run sees.

## The cheapest readiness gate is not having one

dp's browser suite starts the app **in-process on an ephemeral port** instead of orchestrating
containers: the Playwright global setup builds the bundle, loads a checked-in config override
via an env var, creates the schema in an in-memory SQLite database, seeds it, calls
`listen(0)`, and writes the assigned port to a state file the workers read. No health endpoint,
no polling, no sleep, and therefore no timeout path — the setup resolves or throws, and the run
fails fast [confirmed, 2026-09-23, reported from that repo's workflows and config]. PR runs
~2 min, weekly browser runs ~6-8 min.

Three companions to it, all worth copying:

- **Shorten real waits, don't fake the clock.** A `timers` config block (nudge delays 50ms, poll
  windows 10s) plus an outright ban on `waitForTimeout` took that suite from ~9.5 min to under a
  minute. Real timers still fire on their own schedule, so the code under test is the real code.
- **One checked-in override file with only safe values**; real credentials come from the CI
  secret. Not a second config tree.
- **One seeded group per spec with explicit ids**, so specs cannot leak state into each other.
  Fixtures synthetic; nothing production-reachable from CI.

Where it stops: that design works because the app is one process with a swappable in-memory
backend. A stack that genuinely needs containers still needs compose, pinned images and a
readiness gate — take the principles, not the shortcut. And note what their setup pays for
elsewhere: the suite makes real third-party API calls, so it is not hermetic, runs only 2
workers, needs a 180s per-test timeout and a credential to run at all.

## Code review: what the evidence actually supports

Literature pass, 2026-09-23. Numbers with their caveats, because several are weaker than their
reputation. The `pr-check` playbook's rationale section cites this entry.

- **Size.** Google: 100 lines reasonable, 1000 "usually too large"
  (google.github.io/eng-practices, developer/small-cls). The familiar 200–400 lines / ≤500
  LOC-per-hour / 70–90% defect-discovery figures are the 2006 Cisco–SmartBear study: pre-CI,
  C-family code, published by a tool vendor. Use as a heuristic, never quote as a law.
- **Latency.** Respond within one business day; Chromium asks reviewers to check 2–3x/day and
  add a second reviewer after two days. Speed of *each* response matters more than total elapsed.
- **What humans are bad at.** Bacchelli & Bird (ICSE 2013): ~75% of review comments concern
  maintainability, only ~20–25% functional defects. Attention drains into what a linter should
  own — which is the empirical case for the deterministic gate, and for Google's "Nit:"
  convention on non-blocking polish. Google's own answer is Tricorder: 110+ analyzers feeding
  results into the review.
- **What needs judgment** (eng-practices, reviewer/looking-for): does it improve overall code
  health even if imperfect; does it do what the *issue* asked; complexity and comprehensibility;
  naming; do comments say *why*; are these the right tests; API/semver blast radius.
- **Checklists: evidence is thin.** The studies are student populations (e.g. Chong et al.,
  ICSE-SEET 2021); no strong industrial result shows they raise defect yield. Treat a checklist
  as a routing device for what humans look at after CI, not as a detector.
- **Reviewing LLM-authored code.** Veracode 2025: 45% of AI-generated samples introduced an
  OWASP Top 10 flaw; XSS defended in 14% of relevant cases; JavaScript the worst language at
  ~43% failure; **security did not improve with newer or larger models**. DORA 2025: AI raises
  throughput and correlates with higher instability. GitHub states its own review bot "is not
  guaranteed to spot all problems". Practical focus, in order: (1) delete-the-fix — would the new
  test fail without the change? Google: "tests do not test themselves"; Node.js requires a test
  that fails before and passes after. Nothing in CI does this for you. (2) Does every new
  dependency exist, and is it the intended package — hallucinated names are a live supply-chain
  vector. (3) Does the change do what the *issue* asked, not what the prompt said.
- **JS/TS gates worth having.** `typescript-eslint` `recommended-type-checked` (the type-aware
  rules `no-floating-promises` / `no-misused-promises` catch the real async bugs; they need
  `parserOptions.project`, so they are slow); `tsc --noEmit` with `strict`; a ratchet on
  `any`/`ts-expect-error` counts rather than a hard gate; DOM-sink rules (`innerHTML`, `eval`,
  `new Function`, string `setTimeout`, `dangerouslySetInnerHTML`) in preference to generic
  security lint, which is high-noise. `npm audit` on production dependencies only — its defaults
  (devDependencies, unreachable transitives) are the main false-positive source.
- **The seam nothing lints:** serialization and validation between an SPA and its API. Neither
  side's tooling reads both ends; it needs a named reviewer viewpoint.

## Size container memory caps against the shared slice, not per run

Reported by the server's director session, 2026-09-28/29 [confirmed by that session]. Two caged
agent runs were each started with `--memory 6g`, a defensible cap for one run on its own.
Together they claimed 12 GiB of a 16 GiB systemd slice that also held every Claude session,
Ollama and Docker itself, and the slice sat at its 14 GiB `MemoryHigh` all night.

**Rule:** the sum of all container caps plus the measured host overhead (about 2–3 GiB on that
server) must stay at or under the slice's `MemoryHigh`. If it does not fit, stagger the runs.

## Memory throttling is the early warning; an OOM kill is the post-mortem

Same runs, 2026-09-29 [confirmed by the server's director session]. The slice's
`memory.events` `high` counter went from 313 to 11,294 in the minute the second cage started,
while `oom_kill` stayed at 0. A watch that looks only for OOM kills sees nothing while this
happens [concluded].

**Rule:** watch the `high` counter in `memory.events`, and `memory.current` against
`MemoryHigh`, not only OOM kills.

## The process the kernel kills is not the one that caused the pressure

Reported by the server's director session, 2026-09-29 [concluded by that session]. At the
slice's hard limit the kernel picks a victim inside the slice. The most likely victim is a
long-lived Claude session, not the cage that caused the pressure. The run nobody is watching
causes the trouble, and the session someone is working in pays for it.

**Rule:** the unattended, capped job should have the least claim on the shared slice, so that
pressure it causes lands on it and not on its neighbours.

## Verify containment by cgroup, not by description

Reported by a project director, confirmed by the server's director session, 2026-09-28/29. An
OpenCode session ran uncaged, as the agent user, for about 7 hours. It had the live OpenRouter
key, deploy keys, the GitHub CLI token and all real repos within reach. It reviewed wiki-polis
PRs in real worktrees and wiped an uncommitted fix. Nothing about how the run was described
said "uncaged"; only the host could.

**Rules:**
- **Check the cgroup path of the running process** (for example `/proc/<pid>/cgroup`):
  `docker-<id>.scope` means contained, `session-N.scope` means it runs in a login session.
- **Add that check to the watcher's baseline,** so it runs every time, not only when something
  already looks wrong.

## A watcher's state report runs ahead of reality when someone else launched the run

Reported by the server's director session, 2026-09-29 [confirmed by that session]. The watching
session was told a cage was live when none existed yet. Later it was told that run 1 had
exited, when it was still running at 5h02. The reports described the plan, not the host
[concluded].

**Rule:** the watcher reports what it can observe on the host, and says so explicitly when that
contradicts the brief. A brief says what should be running; only the host says what is.

## A wall-clock cap passed as an environment variable is not a cap

This happened twice.
- 2026-09-29 [confirmed by the server's director session]: run 1 was launched with
  `-e HOURS=3 -e TUI=1` and ran 5h02, because the interactive code path ignored the variable.
- 2026-09-29/30 [confirmed by the sessions coordinator]: a relaunch of the main lane used a
  bare `docker run` with no outer `timeout`. It ran 2 hours past its 24-hour cap and produced
  nothing useful in those 2 hours, until it was stopped by hand. Its final bundle was written
  from the Docker volume afterwards.

**Rules:**
- **Enforce the cap in the launcher, outside the container:** `timeout` around the run, or a
  companion process that issues `docker stop` at the deadline.
- **A relaunch goes through the same launcher as the first run** [concluded]. A hand-typed
  `docker run` drops every cap the launcher adds.

## Decide the watcher's permissions before the run starts

Reported by the server's director session, 2026-09-29 [confirmed by that session]. Asked "is it
doing anything useful?", the watching session could not answer. Every meaningful check needed
`docker`, `sudo -u agent`, or reads in the folder the run writes to, and its read-only
exception covered none of them.

**Rule:** agree a fixed, read-only allowlist for the watcher at launch: the exact commands it
needs to judge progress. Then the questions that come up during the night can be answered
without a new approval.

## Emergency authority must exist before the emergency

Reported by the server's director session, 2026-09-29 [confirmed by that session]. Stop-only
authority for the watcher was proposed at 15:18. It still had not been granted when the slice
hit its memory throttle at 22:23.

**Rule:** an unattended run either has a pre-agreed stop condition, decided before launch (what
triggers it, and who or what may stop the run), or it effectively has none. Asking for
permission at 03:00 is not a plan. The director followed this up with a written kill-order
proposal.

## Bash reads a running script as it goes: never overwrite one in place

Observed by the sessions coordinator, 2026-09-29, correcting its own first claim [concluded].
The first claim was that a running lane keeps its launcher script in memory. It does not: bash
reads a script piece by piece while executing it. Overwriting a running `cage-overnight.sh` or
`queue.sh` can derail the lane that is running it.

**Rule:** never overwrite a script that is running. Ship the change under a new filename, or
wait for the next launch.

## A child in a `while read` loop drains the loop's stdin, and a stub that ignores stdin hides it

Diagnosed by a project director, fixed and tested with the sessions coordinator, 2026-09-29
[concluded]. A night's review run stopped after 1 of 23 PRs. OpenCode, started inside the
`while read` loop over the order file, read the loop's stdin and so consumed the remaining
lines. The runner's test used a stub in place of the model, and the stub never read stdin, so
the test passed with the bug present.

**Rules:**
- **Give every model and gate call inside such a loop an empty stdin** (`< /dev/null`).
- **Make the test stub read stdin,** as the real tool does. The test then fails when the bug
  returns; this one was shown to fail without the fix.

## A replication must fail on an assertion, not on an import error

From a project director's test plan, 2026-09-28 [concluded], and a later real run reported by
the sessions coordinator [confirmed by that session]. "Fails on base, passes on the PR" proves
nothing if base fails because the test cannot import. On the real run, all 6 replications of
behaviour bugs were genuine. The test-only and refactor items were hollow: a test that a file
exists, a `hasattr` check. One "fail on base" was an unrelated i18n guard failing.

**Rules:**
- **Check the failure reason, not only the exit code.** Base must fail on an assertion in the
  new test; a failure anywhere else in the run does not count.
- **A replication is evidence for behaviour bugs.** For test-only and refactor items, read the
  test: one that checks existence or attributes passes on any code.

## `opencode run` as an unattended read-only reviewer dies on its first rejected shell call

Reported by a project session, 2026-09-26 [concluded]. In non-interactive mode, a shell command
outside the plan agent's allowlist is auto-rejected, and the rejection ends the whole run: 3 of
4 review runs died this way. Switching to `--agent explore` does not help. `explore` is a
subagent, so the run silently falls back to the permissive `build` agent.

**Rules:**
- **Define a primary, read-only `review` agent** whose forbidden commands are `deny`, not `ask`.
- **Untested:** whether a `deny` lets the run continue where a rejected `ask` ends it. Check on
  a throwaway run before relying on it.

## A command hook that matches keywords anywhere blocks the wrong commands, and a hard block cannot be approved

From a project director's report and the sessions coordinator's rewrite, 2026-09-27/28
[concluded]. A hook meant to stop database writes matched "drop" or `.run(` anywhere in the
command. Tested on 10 commands, it produced 5 false blocks and missed 4 real writes. Because it
returned a hard `block`, Lodewijk's explicit yes could not let a legitimate command through.

**Rules:**
- **Match only when a database client is actually being invoked,** not on words anywhere in
  the line (see also "Match `ssh` as the command, not as a substring" in the Claude Code lessons).
- **Ask rather than block,** so the human can approve. Keep hard blocks for whole-database drops.

## A worktree shares `.git`: give each untrusted run a fresh clone

Recorded by the sessions coordinator in a cage packet, 2026-09-28 [concluded]. A git worktree is
not a separate repository; it shares the main checkout's `.git`. A cage given a worktree of the
server's main checkout can therefore reach that checkout's real hooks and refs.

**Rule:** every cage run gets its own fresh clone, never a worktree of a checkout that people
or other agents use.

## A protocol line meant for one step reaches every step

Reported by the sessions coordinator, 2026-09-29/30 [confirmed by that session]. A shared run protocol said
"run the test command to check your work". The reviewer steps read the same protocol and reran
the full suite (131 s per run) inside a 15-minute cap. 8 of the run's review steps timed out
(about 1 in 6), the security review among them twice, and no verdict recorded which reviews
were missing.

**Rules:**
- **Role-specific instructions go in the role's own file,** not in the shared protocol.
- **Give reviewers the gate's result** instead of having them rerun the gate.
- **Record, per verdict, which reviews completed.** No verdict without the security review.

## Unattended jobs finish far under their caps: plan the queue by work, not by caps

Reported by the sessions coordinator, 2026-09-30/10-01 [confirmed by that session]. Seven unattended jobs used
about 15–40% of their caps, and two lanes then sat idle for about 14 hours. The first queue
runner also recorded a job that did not fit the remaining time as permanently skipped, so a
restart with more time would never have run it.

**Rules:**
- **Queue more work than the caps suggest.**
- **The runner logs IDLE once and leaves non-fitting jobs WAITING,** not skipped.
- **The watcher reports an empty queue,** so idle lanes are seen when they happen.

## Write checksums last, and leave out the log that is still being written

Reported by the sessions coordinator, 2026-09-29/10-01 [confirmed by that session]. A launcher wrote `SHA256SUMS`
and then appended to `cage.log`, which the checksum file covered. Every transfer of the bundle
then failed verification on `cage.log`. A check that always fails on one file trains people to
ignore checksum failures, the real ones included.

**Rule:** write the checksum file as the last step, and exclude any file still being written to,
such as the launcher's own log.

## Newer Ubuntu releases ship Rust coreutils: GNU shorthand can fail

Reported by the sessions coordinator, 2026-09-30 [confirmed by that session]. Newer Ubuntu releases ship
the Rust reimplementation of coreutils (uutils). On such a server `tail -3` fails with
"unexpected argument"; `tail -n 3` works.

**Rules:**
- **Use the explicit option forms** (`tail -n 3`), and do not assume GNU-only flags such as
  `df -BG` are available.
- **Scripts that parse such output should degrade safely** when a command fails.

## A free model's built-in review panel is not an independent check

Reported by the sessions coordinator, 2026-10-01 [confirmed by that session]. A free model (Space Bunny
Free, run through OpenCode) reviewed PRs with its own review panels: 3 reviewers plus a
cross-review per PR. They found 0 of 4 known issues: a `.py` file in a docs-only PR; a
contradiction in the docs; an OAuth claim that glossed over a known security finding; and
evidence that proved nothing. It was strong at fact-checking claims against code, and weak on
omissions (it reported "0 lost" when 9 were lost), on numbers in prose, and on hollow tests.

**Rule:** treat its output as a draft. Every job gets an independent check, and nothing it
writes goes public.

## The cage thinks, approved routes fetch

A pattern from a caged research run, 2026-09-29 [concluded]. The cage has no web access. It
writes the sources it wants as entries in a request list. A separate, approved pipeline fetches
them under robots.txt and rate limits, with archive fallbacks and the project's User-Agent. A
second cage round then builds on what was collected.

**Rules:**
- **The cage never fetches;** it only asks.
- **Check network use in the cage's logs afterwards.** "No web" in a cage is enforced only by
  its instructions unless the network is actually cut.

# Data pipelines

## A green QA check only proves what it compares

Reported by a data-project director, 2026-09-27 [confirmed by that session]. A runbook's step
"after 7b, re-run reduce" left out re-running the article dimension table (`dim_article`). The
reduce passed QA, yet it silently dropped all 10,078 newly admitted articles as unmatched in
that table.

**Rule:** make each check compare the thing its step was meant to change (here: the newly
admitted articles are in the output). A check that only ever passes proves nothing; show it
can catch the failure it is there for.

## Rehearse against the checkout you will actually upload from

Reported by the same director, 2026-09-29, from a job packet [confirmed by that session]. A
rehearsal that read the checkout the operator would upload from showed that the pass-3 scanner
existed only in a worktree, not in main. The upload would silently have re-run pass 2. Written
warnings had missed it.

**Rule:** rehearse the upload from the exact checkout and path the operator will use, and
check there that each file the launch runs is the new version. This extends "A remote job
packet's preflight must check every file the launch runs" above.

## Test a filter predicate on data; reading it is not enough

Reported by the same director, 2026-09-29 [confirmed by that session]. A filter meant to keep
"only pages that carried a file" used `n_located`. That column counts located revisions, not
files, and is at least 1 on every parsed page, so the filter would have kept all 2.47M pages.

**Rule:** run every filter on real data before the full job, and check how much it keeps and
what.

# Test runs

## Check that the browser launches before planning browser tests

Reported by a dp session, 2026-09-26 [confirmed by that session]. In a fresh worktree,
`chromium.launch()` failed with "Executable doesn't exist", so `npm run test:pw` and headless
screenshots could not run. The browser install writes outside the repo (on macOS, to
`~/Library/Caches/ms-playwright`), so it needs an explicit approval in the middle of the work.

**Rule:** a session that plans an e2e or Playwright step checks at the start that the browser
launches, and puts the install in its single upfront permission request.

## A chained `npm test` hides later tiers; skip credential tests loudly

Reported by a dp session, 2026-09-26 [concluded]. The project's `npm test` chains its tiers
with `&&`. Two integration tests always fail without Google credentials, so the chain stops
before the smoke tests, and a red local `npm test` cannot tell you whether smoke passed.

**Rules:**
- **Skip credential tests when the credentials are absent,** and print why they were skipped.
- **Or run the tiers independently** and report each one.

## Repro scripts that create external resources need a hard timer and cleanup on every signal

Recommended by the sessions coordinator after a dp session's question, 2026-09-26
[concluded]. The session's repro scripts created real video meetings, and the question was how
to stop stray meetings being left behind.

**Rules:**
- **Every repro script gets a hard timer,** and signal handlers that run the same cleanup as a
  normal exit.
- **Register the cleanup before creating the first resource.**
- **Before reporting done,** check for leftover node or Chromium processes from the project's
  worktrees.

## `git pull --ff-only origin main` on the remote silently misses a package on a feature branch

Reported by a data-project director, 2026-10-20 [confirmed by that session]. A runbook told the
operator to update the remote checkout with `git pull --ff-only origin main`, but five commits of
the package (including a new allowlist) existed only on a feature branch. The pull succeeded,
the scanner would have read the old allowlist and printed a clean DONE. It was caught before
anything was pasted.

**Rules:**
- **The runbook names the branch and the commit the package is on,** and the preflight checks
  out and verifies that exact commit, not `main`.
- **It lists the sha256 of every shipped file,** data files such as allowlists included, and
  the preflight checks them on the remote before launch.
- This extends "Rehearse against the checkout you will actually upload from" above: a
  successful pull is not evidence that the right files arrived.

## A Toolforge job cannot launch other Toolforge jobs

Reported by a data-project director, 2026-10-20 [confirmed by that session]. A packet used a
controller job to start its step jobs. The `toolforge` CLI is not available inside a running job,
so the controller could not launch anything. Its guard refused before writing any output, so it
failed safely, but the run had to be restarted by hand.

**Rule:** chain jobs from the bastion (a launcher script run by the operator) or through the jobs
API, never from inside a job. Rehearse the launcher itself, not only the steps.

## A session scratchpad is not durable: commit any script whose number you record

Reported by a data-project director, 2026-10-24 [confirmed by that session]. Eleven analysis
scripts written in a session's scratchpad were wiped when the session restarted. Only the numbers
transcribed from them survived, including the evidence behind a rewritten validation gate.

**Rule:** the moment a number enters a finding, a registry row, a spec or a correction, the
script that produced it is committed to the project's `scripts/` (or the analysis folder),
together with its input checksums. The scratchpad is for throwaway work only. A number whose
producing script is gone is unverified, however carefully it was copied.

## Unused weekly quota expires at the reset: keep token-heavy work ready, and raise it a day ahead

Observed by the sessions coordinator, 2026-11-14 [confirmed: plan usage read 40 minutes before
the reset]. Weekly quota was 46% used with 40 minutes to go, and the user asked to use the rest.
Nothing was ready to start. The candidate jobs either waited on the user's own steps (a re-triage
needing four commands he types) or were not defined (proto "updates"). The cloud sessions the
user picked could not be started from a phone session: the app starts a session on another
repository only from the Code tab. The coordinator's list of open PRs to review was also out of
date: one had merged that morning. The reset passed with the quota unused.

**Rules:**
- **Check plan usage at the first turn of the day and again about 24 h and 3 h before the
  weekly reset.** If much is unused, tell the user then, not in the last hour.
- **Keep a short ready queue of token-heavy work that needs no approval to start:** read-only
  reviews, triage and literature passes. Each item has a written brief and a named repository,
  so it can start in one step.
- **Get the user's go while they are at the desktop,** or have them start cloud sessions there.
  A Remote Control (phone) session cannot start a session on another repository.
- **Before proposing a review, re-check the PR's state.** A list made yesterday is stale.
- Work that starts after the reset counts against the new week. Only work started before the
  reset uses the old quota.

## A storage exception in a registry must cite its ruling and how it was verified

Reported by the Toolforge director, 2026-11-14 [confirmed by that session against its own log].
A registry row said one T5 year's day-level shards could have a single copy "because cday
rebuilds byte-identical … (Lodewijk, relayed by ADR-03 2026-11-05)". The Toolforge director's
log has no such ruling. On 11-05 the user had said no delete without a copy, and the bucket
became that copy. The rebuild had never been tested. The coordinator then repeated
"exactly rebuildable" in its own log entry the same day.

**Rule:** any exception to the copy rule written into a registry names (1) where the ruling was
typed (whose chat, date, log entry) and (2) how the claim behind it was checked: a test with its
result, or the words "design only". "Relayed by X" alone is not a source. "Rebuildable" counts
only with a rebuild that was run and compared. Until then it is a plan, not a copy.

## Archiving a worktree session deletes its gitignored files, with no backup

Reported by the coordinator and a project director, 2026-11-15 [confirmed: storage report shows
no kept worktree; the folder went from 12 GB to 0 B in the same minute as the archive].
The coordinator archived a finished session after it replied "safe to archive". The desktop
app's archive returned the session's worktree to its reuse pool. That deleted every untracked and
gitignored file (12 GB of `.claude/` working data) but left the empty directories. The app
keeps a worktree after archiving only for uncommitted *tracked* changes, so nothing was kept.
The data was very likely a copy of the main checkout's `.claude/`, so little or nothing unique
was lost, but nobody could prove that afterwards. The "safe" reply had been judged from git
state and a sample of files. A standing rule ("never archive a session with a worktree") was in
the state file but not in the archive checklist.

**Rule:** before archiving a session that has a worktree, list its gitignored and untracked
files with sizes. Copy anything not already elsewhere (to the main checkout or the drive, with a
byte check), or leave the session open. "Safe to archive" from the session itself is not enough:
it must say it checked ignored files, not just `git status`.

## Hague cannot fetch YouTube media, and some public sites answer bots with a JS challenge

Reported by a hague research session, 2026-11-17 [confirmed by that session: every YouTube media
request from hague's address got "Sign in to confirm you're not a bot"; `yt-dlp --flat-playlist`
metadata still worked; a public-body site served a JavaScript challenge (HTTP 401) to curl, and
its Wayback copies worked]. The session routed around neither block and asked Lodewijk.

**Rule:** treat a bot wall as an access decision by the host, not as an obstacle. The only ways
past a YouTube sign-in wall are cookies (a sign-in), tokens or proxies, which are circumvention
and are off the table. For a blocked public page use the Internet Archive route (`id_` URLs).
For YouTube media, a fetch route has to be approved by Lodewijk first (on the Mac, or as a job he
starts) and written into the connector library. Until then, a packet that needs YouTube media is
not launch-ready on hague. Check this when the packet is built, not after it fails overnight.

## A delete guard must count the copies that remain, not check that one copy exists elsewhere

Reported by the drop director, 2026-11-19 [confirmed in the data register: nine items moved from
the compute host to the Research drive the same day and became drive-only the moment the host
copies were deleted; one of them, a 0.5 GB article-topic cache, had no laptop original and was
not on Hugging Face, so the drive tar became its only copy]. Every step looked correct on its own:
the move was verified file by file, and the delete rule was "the item is verified off the host".
But "verified somewhere else" is not "two verified copies remain". The approval line the owner
saw did not say how many copies would be left.

**Rule:** before any delete, count the verified copies that would remain, from the data register
(only copies that are present and byte-verified count; the drive never counts as the only one).
Require at least two, or a recorded exception citing the owner's ruling. Print that count in the
delete line the owner approves: "deletes X; remaining verified copies: drive, laptop (2)". A
relayed "copy exists" from another session is not the count; the register is.

**Guard:** `data_locations_check.py --before-delete DATASET_ID@LOCATION` (repeatable; all targets
are removed together before counting) prints that line and exits 1 when fewer than two would
remain, or only drive copies would, unless the dataset is a cache with a rebuild recipe or a row's
note records `delete-exception: <ruling>`. Its tests replay this case; under the old "verified
elsewhere" rule five of them fail.

## Orphaned log-filter processes are invisible until a memory event turns them into load

Reported by the WWK-03 Hy13 session, 2026-11-22, with the host data from the hague director
[confirmed by the director's status file: hague load 1.57 at 20:37Z, 69 at 23:07Z, 83 at 23:27Z;
the first app probe at 23:41:50Z; peak about 195, 98 % kernel time]. A long job's memory peak
pushed the compute host into swap. Underneath it, 16 `ugrep --line-buffered` filters left from
agent Monitor pipelines dated 2 to 17 October were still alive, reparented to init (ppid 1), and
spun in kernel time once memory got tight. An 11-hour job step was starved for about 8 hours and
timed out. Load fell to about 1 only after those filters were killed. Nobody had owned or seen
them for seven weeks.

**Rule:** a pipeline such as `tail -f | grep --line-buffered` or a Monitor filter outlives the
session that started it when that session dies. On every long-lived host, include a sweep for
processes with no live parent in the regular check-ins, not just after an incident:
`ps -Ao pid,ppid,etime,time,command | awk '$2==1'`. Look for filters, `tail -f`, and anything with
a large accumulated TIME. The hague director now runs this sweep at each check-in. (The Mac
had none on 2026-11-22.)

**Related amplifier:** the desktop app keeps its remote-host SSH links with `ControlMaster=yes`,
`ControlPersist=no` and `ConnectTimeout=30`. On a loaded host its `server --version` probe
hangs and the app opens another, so 52 piled up and made the spike worse. They didn't start it.
The coordinator advised against disabling the entries, because every agent session on hague
runs through them. Keep the host from spiking instead: memory exceptions end with the run they
were granted for, the orphan sweep runs at each check-in, and a watcher alerts on probe or load
growth. (WWK-03 first advised removing the entries, then withdrew that advice once it learned
what depends on them. That withdrawal is itself an example of the next lesson.)

## Classify what a pattern matched before you publish the count

Same incident. Counting the app's SSH connections by grepping `ps` output for the control-socket
path gave 51. Only 6 were connections. The other ~45 were app helper processes that carry the
path in their arguments [confirmed: WWK-03's retraction; the coordinator's own `ps` showed 6].
The 51 had already been relayed toward Lodewijk before the correction caught up. A wrong number
passed between sessions spreads at machine speed and reaches the user ahead of its correction.

**Rule:** before reporting a count from a pattern match, look at what matched and count by the
property you mean. For processes that means the executable, e.g.
`ps -Ao pid,ppid,etime,command | awk '$4=="/usr/bin/ssh"'`, not the arguments. If a count has
already been sent, the retraction goes to every recipient, not only the next one.

## A slope gate and an overlap gate can both pass a pure level shift

Reported by the WWK-03 Hy13 session, 2026-11-22, from the T110 placebo [WWK-03 confirmed by
recomputing from the bin means; commit 7007a0ac in the drop repo]. Across every decile of the
exposure variable, the placebo outcome on a null window rose by the same amount, about +0.006.
The registered gates tested the slope against exposure and the overlap between groups. A uniform
shift moves every bin together, so it has no slope and the groups still overlap. Neither gate
could see it, and every difference-in-means-against-exposure test in that register had the same
blind spot. The same recomputation showed that the slope artifact sat only in the extreme top
deciles, which no gate checked either.

**Rule:** when a register gates on a slope or a group difference, add a level gate as well: the
mean change on the null or placebo window must be indistinguishable from zero. Also look at the
per-bin values, not just the fitted slope, before reading a verdict. A failure confined to one
tail, or a uniform shift, is a finding in its own right.

**Amendment, same day (WWK-03, T110 AMENDMENT, drop repo 975ae640):** the T110 window was not
null. A daily trace of 2026-08-03..31 found an unexplained step on 2026-08-08 (about −0.19 in the
daily slope, flat for the nine days after). The known 08-17 lazy-loading switch showed up in the same
trace, which confirms the instrument picks up real events [WWK-03 confirmed]. The placebo window
08-03..09 vs 08-10..16 straddles the step, so its failure says nothing about the instrument. T88
was withdrawn on the strength of that placebo. Both briefs had justified the window as
"weekday-balanced by construction". The level-gate rule above stands, plus a second one: **before
a window serves as a placebo or baseline, trace the series day by day across it and check that no
step falls inside it.** A balanced design does not make two weeks interchangeable if the process
changed between them, and a two-week comparison cannot see that it did.

**Second amendment (WWK-03, T112 RESULT, drop repo 40587a5e):** the step screen WWK-03 then
pre-registered, blind to the block it would run on, passed its positive-control gate for the wrong
reason. Both known switches (2026-04-20, 2026-05-11) fell on Mondays, and the jump it flagged at
04-20 was smaller than an average Monday. The weekly cycle contaminated both the test statistic and
the noise estimate it was compared against [WWK-03 confirmed]. Under a weekday-balanced screen
neither date shows any change, while the 08-17 lazy-loading switch shows at 41.2 SE, so those two
dates are not positive controls for image-request instruments [WWK-03 concluded]. The same
registration's baseline-selection rule cannot be met by any block of this data, for the same reason.
The balanced screen then dated a second unexplained step, 2026-05-01, inside a decline the register
had carried as "late April to late May, mechanism unknown". Rule: **a pre-registered threshold on a
seasonal series must handle the seasonality inside the statistic, and the positive controls must not
share a phase of the cycle.** Pre-registration guards against choosing after the fact; it does
nothing for a flaw in the statistic itself, and a gate that passes on calendar-confounded controls
is worse than no gate, because it is trusted.

## Test an alarming inventory finding before you report it to other sessions

*2026-11-23 · source: WWK-03, relayed by WDR-00 (wikipedia-drop-2026 sessions)*

In a multi-session setup a report fans out: the receiving session passes it on, and others start
acting on it, before anyone has re-checked it. A retraction then travels the same path, but later.
That week WWK-03 raised two inventory alarms, a hole in the leadmc data and a char_offset mismatch,
and both turned out to be wrong [WWK-03/WDR-00 confirmed]. The char_offset alarm had already reached
WWK-05 through WDR-00 before it was tested. Re-checks caught both, not downstream analysis, so no
result was built on them; the cost was the other sessions' attention and a retraction to chase.
Rule: **an alarming finding from an inventory or audit is a hypothesis until you have tested it.
Run the cheapest test that would disprove it, then report, with the label that test earned
([confirmed] / [concluded] / [guess]).** If it must go out untested because something is at risk,
mark it untested and say what would settle it.

A related habit held up in the same episode: when WWK-03 re-used WDR-00's drive check, it left the
check under WDR-00's name instead of re-labelling it as its own (drop repo 1888dc3f). A custody record
should name the session that actually performed each check. Re-labelling turns one verification into
what looks like two independent ones.

## A program's self-reported peak memory is silently wrong on one of your two platforms

*2026-11-24 · source: WWK-03, found by ADR-02 (wikipedia-drop-2026 sessions)*

`resource.getrusage(...).ru_maxrss` is in **bytes on macOS/BSD** but **kilobytes on Linux**. Python's
docs note only that the units are platform-dependent, so the idiomatic `ru_maxrss / 1e6` labelled "MB"
is correct on a Mac and **1000x too small on Linux**. A script here printed *"peak RSS 2 MB"* for a job
that `/usr/bin/time` measured at **1.57 GB** [confirmed: `1.57e9 / 1e3 / 1e6` formatted `%.0f` prints
`2`].

Why it survives review: the wrong number is **plausible and flattering**. A 2 MB figure reads as a
lean job, not as a defect, so nobody interrogates it — whereas an implausible number gets caught the
first time anyone looks. It also errs in the dangerous direction: it **hides** memory pressure on the
remote Linux host where memory limits actually bite, while on the developer's Mac, where the figure
happens to be right, there is RAM to spare. A grep of one repo found **44 call sites — 42 assuming
macOS, 2 assuming Linux, and none platform-aware**, so every one of them was wrong on the other
platform. Any historical RSS figure recorded from a Linux run is suspect by 1000x in whichever
direction the divisor assumed.

Two rules:

1. **Make the divisor explicit**: `1e6 if sys.platform == "darwin" else 1e3`. A bare `/1e6` is a
   platform assumption written as arithmetic, which is why it reads as correct.
2. ⭐ **Never size a job from its own self-report.** Measure anything you hand to another host with an
   external tool (`/usr/bin/time -v`) and compare the two figures. This bug was found by a peer
   noticing that two measurements of the same quantity disagreed by three orders of magnitude — not by
   anyone reading the code, which had been read several times by then. Agreement between an internal
   and an external measurement is the cheapest available evidence that a self-reported resource number
   means anything at all; without it, the number is decoration.
