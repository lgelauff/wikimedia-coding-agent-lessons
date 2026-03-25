# Toolforge lessons

## Docs to fetch at project start

- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Quickstart
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Web/Python
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes/Webservices
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/ToolsDB
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Kubernetes/Secrets
- 🤖 https://wikitech.wikimedia.org/wiki/Help:Toolforge/Database/Replicas

🤖 = fetchable via WebFetch at conversation start. 📥 = download and paste in.

---

## Deployment

- **Venv must use the system Python**: `uv venv --python /usr/bin/python3 ~/www/python/venv`. Do not use the project's local Python version. The Kubernetes node runs whatever Python version Toolforge provides (currently 3.13).
- **`webservice restart` must be run from `~`**, not from inside the repo. It fails silently or behaves wrongly otherwise.
- **`toolforge envvars list` masks values** — secrets cannot be retrieved after creation. Keep a local record.
- Updating a running deployment: `git pull`, then `uv pip install --python ~/www/python/venv/bin/python -r requirements.txt`, then `webservice restart`.

## uWSGI

- **`lseek: Illegal seek` in logs** — harmless noise from uWSGI trying to rotate logs on a non-seekable stdout. Filter with `grep -v lseek` when reading logs.
- **`processes=1 threads=8`** is the safe pattern for apps with background threads (avoids cross-process races). Verify Toolforge is not injecting its own `--workers` flag on the command line — check the startup log line starting with `exec /usr/bin/uwsgi`.
- **`logto = /dev/stdout`** is correct for Kubernetes log capture.
- **`webservice restart` must be run from `~`**.

## ToolsDB (MySQL)

- Connect with: `mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud`
- Database naming convention: `s12345__dbname` (credential username + double underscore + your name). The prefix must match exactly or you get "Access denied".
- Create with `CHARACTER SET utf8` to avoid index-size errors on migrations.
- `replica.my.cnf` doubles as credentials for both ToolsDB and replica databases.
- `NOW()` is MySQL-only — use bound parameters (`:now`) with `utcnow().replace(tzinfo=None)` in raw SQL for portability.

## Replica databases

- Replica DBs (`*.labsdb`) are **only accessible from within Toolforge**, not locally.
- Design any code that queries replicas to fail gracefully or skip those steps when not on Toolforge.
