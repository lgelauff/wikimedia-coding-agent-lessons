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
- **Venv must be created inside a webservice shell**: run `toolforge webservice python3.13 shell`, then `python3 -m venv ~/www/python/venv`. A venv created directly on the bastion will not work with `toolforge webservice`.
- **Use plain pip inside the shell**, not uv, to install into `~/www/python/venv`: `~/www/python/venv/bin/pip install -e ~/wiki-polis`. uv is not documented for Toolforge web service venvs and can pull in its own managed Python instead of the system one.
- **Flask apps with `static/` and `templates/` dirs** need `[tool.setuptools] packages = []` in `pyproject.toml`, otherwise setuptools chokes on "Multiple top-level packages discovered" when doing `pip install -e .`.
- **`webservice restart` must be run from `~`**, not from inside the repo. It fails silently or behaves wrongly otherwise.
- **`toolforge envvars create` syntax**: `toolforge envvars create NAME "VALUE"` — no `--value` flag.
- **`toolforge envvars list` masks values** — secrets cannot be retrieved after creation. Keep a local record.
- **Updating a running deployment**: use a `deploy.sh` script that runs `git pull`, `pip install -e ~/wiki-polis`, then `webservice restart` from `~`.

## pip / venv

- **Always run `pip install` inside `toolforge webservice python3.X shell`**, not the bastion shell. The bastion shell activates a different venv than the one uwsgi uses — installing packages there has no effect on the running service. Enter the webservice shell first, then pip install, then exit and restart.
- **The uwsgi log is not inside `src/`** — it is typically at `/data/project/<tool>/uwsgi.log`, one level above the repo.
- **No `sqlite3` CLI on Toolforge** — use Python: `python3 -c 'import sqlite3; c=sqlite3.connect("path/to/db"); ...'`

## uWSGI

- **`lseek: Illegal seek` in logs** — harmless noise from uWSGI trying to rotate logs on a non-seekable stdout. Filter with `grep -v lseek` when reading logs.
- **`processes=1 threads=8`** is the safe pattern for apps with background threads (avoids cross-process races). Verify Toolforge is not injecting its own `--workers` flag on the command line — check the startup log line starting with `exec /usr/bin/uwsgi`.
- **`logto = /dev/stdout`** is correct for Kubernetes log capture.
- **`webservice restart` must be run from `~`**.
- **Long OAuth callback URLs need a larger uWSGI buffer**: Wikimedia OAuth codes are very long and exceed uWSGI's default 4KB buffer, causing "unable to add HTTP_X_ORIGINAL_URI to uwsgi packet". Fix: add `uwsgi.ini` to the repo root with `buffer-size = 65536`. Toolforge picks it up automatically from `~/www/python/src/uwsgi.ini`.

## ToolsDB (MySQL)

- Connect with: `mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud`
- Database naming convention: `s12345__dbname` (credential username + double underscore + your name). The prefix must match exactly or you get "Access denied".
- Create with `CHARACTER SET utf8` to avoid index-size errors on migrations.
- `replica.my.cnf` doubles as credentials for both ToolsDB and replica databases.
- `NOW()` is MySQL-only — use bound parameters (`:now`) with `utcnow().replace(tzinfo=None)` in raw SQL for portability.

## Replica databases

- Replica DBs (`*.labsdb`) are **only accessible from within Toolforge**, not locally.
- Design any code that queries replicas to fail gracefully or skip those steps when not on Toolforge.
