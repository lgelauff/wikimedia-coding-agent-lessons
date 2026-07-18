# Toolforge Lessons - Full Content

## Docs to fetch at project start

- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Quickstart
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Web/Python
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes/Webservices
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/ToolsDB
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes/Secrets
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Database/Replicas

🤖 = fetchable via WebFetch at conversation start. 📥 = download and paste in.

## Deployment

- **`~/www/python` must be a real directory**, not a symlink to the repo. If you accidentally run `ln -s ~/wiki-polis ~/www/python`, all subsequent symlinks (`src`, `venv`) end up inside the repo, breaking everything. Always `mkdir -p ~/www/python` first.
- **`~/www/python/src` is the symlink to the repo**: `ln -s ~/wiki-polis ~/www/python/src`. Toolforge serves `~/www/python/src/app.py`.
- **Venv must be created inside a webservice shell**: run `toolforge webservice python3.13 shell`, then `python3 -m venv ~/www/python/venv --without-pip` (see pip/venv section — `ensurepip` hangs in the pod). A venv created directly on the bastion will not work with `toolforge webservice`.
- **Use plain pip inside the shell**, not uv, to install into `~/www/python/venv`: `~/www/python/venv/bin/pip install -e ~/wiki-polis`. uv is not documented for Toolforge web service venvs and can pull in its own managed Python instead of the system one.
- **Flask apps with `static/` and `templates/` dirs** need `[tool.setuptools] packages = []` in `pyproject.toml`, otherwise setuptools chokes on "Multiple top-level packages discovered" when doing `pip install -e .`.
- **`webservice restart` must be run from `~`**, not from inside the repo. It fails silently or behaves wrongly otherwise.
- **`toolforge envvars create` syntax**: `toolforge envvars create NAME 'VALUE'` — no `--value` flag. Use **single quotes**, especially for URLs: `"https://..."` causes the shell to interpret `://` as a redirect operator and fail silently.
- **`toolforge envvars list` masks values** — secrets cannot be retrieved after creation. Keep a local record.
- **Updating a running deployment**: use a `deploy.sh` script that runs `git pull`, `pip install -e ~/wiki-polis`, then `webservice restart` from `~`.

## pip / venv

- **Always run `pip install` inside `toolforge webservice python3.X shell`**, not the bastion shell. The bastion shell activates a different venv than the one uwsgi uses — installing packages there has no effect on the running service. Enter the webservice shell first, then pip install, then exit and restart.
- **Match Python versions**: use `python3.13` for both bastion and webservice. The bastion runs 3.13; using `python3.11` for the webservice creates a mismatch — running pip from the bastion corrupts the 3.11 venv silently. `python3.13` is the current Toolforge default and eliminates this class of error.
- **`python3 -m venv` (with pip) and `python3 -m ensurepip` hang in the webservice shell pod** — they spawn a subprocess to install pip which the pod's process restrictions block. Workaround: create venv with `--without-pip`, then bootstrap pip with `curl -sS https://bootstrap.pypa.io/get-pip.py | ~/www/python/venv/bin/python3`. This pipes get-pip.py directly into Python without spawning a subprocess.
- **Use `python3 -m pip` not the `pip` binary** — the `pip` binary in the venv can break after failed reinstalls. `~/www/python/venv/bin/python3 -m pip install -e .` is more reliable.
- **`WARNING: Ignoring invalid distribution ~ip`** — a corrupted pip leftover from a failed uninstall/reinstall cycle. The `~ip` directory is a partially-removed pip. Fix from the bastion: `rm -rf ~/www/python/venv/lib/python3.X/site-packages/~ip*` (replace `3.X` with your Python version), then reinstall pip cleanly.
- **For editable installs, `deploy.sh` does not need a pip step** — `pip install -e .` creates a symlink; code changes are picked up automatically on restart. Only run pip again when `pyproject.toml` dependencies change.
- **The uwsgi log is not inside `src/`** — it is typically at `/data/project/<tool>/uwsgi.log`, one level above the repo. If `logto = /dev/stdout` is set in `uwsgi.ini`, use `toolforge webservice logs` instead.
- **No `sqlite3` CLI on Toolforge** — use Python: `python3 -c 'import sqlite3; c=sqlite3.connect("path/to/db"); ...'`

## uWSGI

- **`lseek: Illegal seek` in logs** — harmless noise from uWSGI trying to rotate logs on a non-seekable stdout. Filter with `grep -v lseek` when reading logs.
- **`processes=1 threads=8`** is the safe pattern for apps with background threads (avoids cross-process races). Toolforge injects `--workers 4` on the command line, but `processes = N` in your `uwsgi.ini` overrides it — uWSGI processes `--ini` after CLI args, so the INI wins. Confirm by checking the startup log: `mapped ... for 8 cores` (threads count) and `Operational MODE: threaded` confirm single-process mode.
- **`logto = /dev/stdout`** is correct for Kubernetes log capture.
- **`webservice restart` must be run from `~`**.
- **Long OAuth callback URLs need a larger uWSGI buffer**: Wikimedia OAuth codes are very long and exceed uWSGI's default 4KB buffer, causing "unable to add HTTP_X_ORIGINAL_URI to uwsgi packet". Fix: add `uwsgi.ini` to the repo root with `buffer-size = 65536`. Toolforge picks it up automatically from `~/www/python/src/uwsgi.ini`.

## Node.js / npm builds

- **Use `toolforge jobs run` for `npm install` + frontend builds**, not an interactive webservice shell. Large packages (e.g. `vue-material-design-icons`) cause the shell pod to OOM-crash or hang for 10+ minutes before dying:
  ```bash
  toolforge jobs run npm-install --image node20 --mem 4Gi --command "cd $HOME/www/python/src/frontend && npm install && npm run toolforge:build"
  toolforge jobs logs npm-install
  ```
- **Image short names** for `toolforge jobs run --image` are e.g. `node20`, not `tool-node20`. Check all available images with `toolforge jobs images`.
- **Use `node20` (not `node18`)** for new setups — node18 is EOL and several modern packages (e.g. `@wikimedia/codex`) require `>=node20`.
- **Run as a single line** on the bastion — backslash line continuation (`\`) does not work reliably in the bastion shell and silently drops subsequent arguments.

## ToolsDB (MySQL)

- Connect with: `mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud`
- Database naming convention: `s12345__dbname` (credential username + double underscore + your name). The prefix must match exactly or you get "Access denied".
- Create with `CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci` — not plain `utf8`, which is MySQL's broken 3-byte alias and can't store emoji or some Unicode characters present in MediaWiki data.
- **db_url format for SQLAlchemy**: `mysql+pymysql://<user>:<pass>@tools.db.svc.wikimedia.cloud/<db>?charset=utf8mb4`. The old `mysql://tools.labsdb` format is deprecated — use `mysql+pymysql://tools.db.svc.wikimedia.cloud`.
- `replica.my.cnf` doubles as credentials for both ToolsDB and replica databases.
- `NOW()` is MySQL-only — use bound parameters (`:now`) with `utcnow().replace(tzinfo=None)` in raw SQL for portability.

## Rules & acceptable use

- **All code on Toolforge/WMCS must be OSI-approved open source.** If you don't declare a license, it defaults to **GPLv3** under the Cloud Services Terms of use. Add a root `LICENSE` before deploying. Exceptions: code withheld to protect privacy, and one-time throwaway scripts.
- **Acceptable use test = "benefit to the Wikimedia movement."** Research data collection/processing and analytics are *explicitly* permitted; a public data-exploration tool qualifies. Prohibited: crypto mining, using WMCS as a network proxy/VPN/Tor, hosting proprietary software, mimicking Wikimedia branding.
- **Privacy:** don't collect personal data beyond OAuth username/email + forwarded user-agent; public webservices sit behind an anonymizing reverse proxy automatically. Outputs built from already-public data (page text, revision metadata) carry minimal privacy burden.

## Outbound network / external APIs

- **Outbound internet access is generally available** — tools can call external HTTPS APIs. There is **no blanket egress block** (a common misconception). The proxy machinery in the docs is for *inbound* traffic (TLS termination, reverse-proxying to your web service) and for anonymizing *client-facing* external content (hiding users' IPs), not for your tool's own server-side outbound calls.
- Inbound rate limit: **100 requests/minute per source IP** across all of Toolforge.
- **Still avoid running paid third-party LLM/API pipelines on Toolforge** — not because egress is blocked, but for secrets hygiene (no API keys on shared community infra), cost, and acceptable-use spirit. Run those stages off-infra and import the compact results.

## The bastion is a login node, NOT a compute node

- **Never run heavy compute (bz2/gzip decompression, large-file parsing, scans over the `/public/dumps` mount) directly on the bastion** (`tools-bastion-NN`). It is a **throttled, shared login/submit node**. A single full dump file (~0.7 GB bz2) will wedge your session:
  - the process blocks on an **uninterruptible NFS read**, so `Ctrl-C`/`Ctrl-Z` are *queued* but don't fire until the read returns (can be minutes) — it looks hung;
  - the load can make a **second `ssh` fail or hang** (retry — `login.toolforge.org` round-robins to other bastions);
  - a process started after `become <tool>` is owned by the **tool user**, so from another session you must `become` again before you can `pkill -9 -f <script>`; and **bastions are host-local** — you can only kill it from the *same* `tools-bastion-NN`.
- **Rule: on the bastion, only light commands** — `ls`, a quick `--inspect`/head of one file, and **job submission/monitoring**. Everything else → **`toolforge jobs run …`** (dedicated core, faster, and killable with `toolforge jobs delete <name>`). Even a 2-file "smoke test" belongs in a job. Symptom that you got this wrong: a `--test`/scan that runs >5 min on the bastion with no per-file progress output.
- **`toolforge jobs run --wait` gives up after 600 s (10 min) but the JOB KEEPS RUNNING.** The timeout is on the client *wait*, not the job — you get `ERROR: timed out 600 seconds waiting for job '<name>' to complete` while `toolforge jobs list` still shows it `Running`. So `--wait` is only for jobs you're confident finish in <10 min. For anything longer, launch **detached** (omit `--wait`) and poll: `toolforge jobs list` + `tail -f` the redirected `> $D/<name>.out 2>&1` log. Don't re-run on the "timeout" — you'll start a second copy. (Redirect stdout/stderr to a file so a detached job's progress is readable; job logs otherwise need `toolforge jobs logs`.)

## Webservice vs jobs

- **A tool can run BOTH `toolforge jobs` (batch) and a `webservice` (HTTP) under one account** — same home, same ToolsDB. Exposing a web UI does not constrain the batch build.
- **Keep heavy compute out of the webservice request path** — pods have memory/CPU caps. Precompute derived/indexed tables in jobs; the webservice only queries + renders. A query that's fine offline can time out a web request.
- For **read-only / infrequently-updated data**, prefer a **static export** (job precomputes JSON + client-side viewer, served as static files) over a live backend: no DB-in-request-path, near-zero maintenance, reproducible, can't go down. Reserve a live Flask app for genuinely interactive/stateful features.

## Replica databases

- Replica DBs (`*.labsdb`) are **only accessible from within Toolforge**, not locally.
- Design any code that queries replicas to fail gracefully or skip those steps when not on Toolforge.
- The old `*.labsdb` hostnames (e.g. `commonswiki.labsdb`) are being migrated to `*.analytics.db.svc.wikimedia.cloud` (e.g. `commonswiki.analytics.db.svc.wikimedia.cloud`). As of April 2026 both aliases still work on Toolforge, but the `.labsdb` aliases may be dropped — prefer the new hostname in new code.
