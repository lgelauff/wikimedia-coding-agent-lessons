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
