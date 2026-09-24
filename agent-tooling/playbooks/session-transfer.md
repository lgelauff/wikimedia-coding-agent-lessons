# Session-to-session data transfer

How one agent session sends data files to another, and only after the coordinator has
checked and approved it. The script is [`scripts/transfer.py`](../scripts/transfer.py), a
member of the `deliver.py` family. The design (2026-09-24) lives in the agent hub notes.

**Parties:** the **sender** has the files. The **coordinator** is the Mac sessions
coordinator. The **receiver** will use the files. The **mediator** is `transfer.py deliver`,
installed root-owned. **Lodewijk** approves as described below.

**Only the same-machine Mac route is built.** Cross-machine (Mac ↔ hague) is a stub that
refuses with "cross-machine route not built: needs Lodewijk's design review".

## Who approves

- **Same machine, overnight:** the coordinator's approval is enough. Overnight means an
  unattended run Lodewijk launched (overnight-run LAUNCH) or a window he has said he is
  away for.
- **Same machine, otherwise:** the coordinator runs the checks, then asks Lodewijk in its
  own chat. The transfer goes ahead only on his yes.
- **Cross machine: always his permission prompt**, overnight included. An overnight job
  that needs a crossing gets it approved at launch time.

## The five steps

**1. Request (sender).** Never write the manifest by hand:

```bash
transfer.py request --slug <slug> --from-session <me> --to-session <them> \
  --to-machine mac --to-harness claude-code --data-class internal \
  --dest ~/dev/<repo>/data/<subdir> --why "<one line>" --source-after keep  FILE...
```

This writes `~/agent/transfer/requests/<YYYY-MM-DD>-<slug>.json` with the size and sha256
of each file. It refuses `raw-pii`, anything under `~/Data_pii`, symlinks, dotfiles and two
files with the same name. SendMessage the coordinator the path. Stage nothing yet.

**2. Check (coordinator).** Run `transfer.py check <id>` (add `--json` for machine output).
It prints PASS / FAIL / UNMEASURED with numbers for each check: data class vs receiver,
receiver named, size cap, sources still matching, dest inside the repo's gitignored `data/`,
disk used after the transfer, and duplicate sha256 or names at dest. It does not decide.
Two checks are yours: run the secrets scan and charset-hygiene on text files, and confirm
the receiver exists and expects the files. Thresholds come from
`~/agent/transfer/limits.json` (`{"disk_max_used_pct": 80, "max_request_bytes": 5000000000}`).
If that file is missing, the report says it is using **provisional defaults**.

Then write the decision yourself as `~/agent/transfer/decisions/<id>.json`:

```json
{"id": "<id>", "decision": "approved", "date": "YYYY-MM-DD", "approved_by": "lodewijk",
 "manifest_sha256": "<from the check output>", "checks": "<the report, or a summary>"}
```

`approved_by` is `lodewijk`, or `coordinator (overnight)` under the overnight rule. The
mediator refuses a decision whose `manifest_sha256` does not match the manifest, so a
manifest edited after approval is refused.

- **Approved:** message both sessions.
- **Denied means returned to the sender, with reasons.** Write `"decision": "returned"`.
  Message **only the sender**, naming every failed check, its measured value and what would
  pass. Nothing is staged and the receiver is not involved. The sender fixes the request
  (split it, drop a file, reclassify it, free space, or pick another dest) and resubmits
  under a new slug with `--supersedes <returned id>`. A request that cannot be fixed within
  the rules goes to Lodewijk through the coordinator. The sender never goes around the
  coordinator.

**3. Stage (sender, after approval).** Copy with `cp`, never `mv`, into
`~/agent/outbox/transfer-<id>/`, with exactly the files in the manifest and nothing else.
Plain `deliver.py` skips `transfer-*` folders.

**4. Deliver (mediator only).** `transfer.py deliver` takes no arguments. For each
`transfer-<id>/` it requires an approved decision and hashes that match the manifest. It
refuses symlinks, overwrites, extra or missing files, and `raw-pii`, and skips dotfiles.
Each file is hashed while it is copied into `~/agent/inbox/transfers/<id>/`. The outbox
folder is emptied only once every file has arrived and verified. Otherwise nothing moves.
Agents never move data out of the outbox themselves.

**5. Receive and close (receiver).** `transfer.py receive <id>` checks the hashes in the
inbox and copies the files into `dest`. `dest` must be inside a git repo's `data/`, and
git must ignore every file that lands there. It refuses overwrites and symlinked path
components, then marks the transfer done in `~/agent/transfer/done/<id>.json`. The sender
deletes its source only if `source_after` is `delete`. The coordinator appends one line to
`~/agent/transfer/log.tsv`.

## Boundary or convention

On the Mac every session runs as the same user, so the decision file is a **convention**:
an agent could forge one. The real boundaries are the root-owned mediator, the fact that
agents have no ssh, and `~/Data_pii`, which every agent is denied.

Exit codes: `0` ok · `1` refused, failed check or partial · `2` could not run.
