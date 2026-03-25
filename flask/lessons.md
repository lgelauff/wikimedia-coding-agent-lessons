# Flask lessons

## Docs to fetch at project start

- 🤖 https://flask-migrate.readthedocs.io/en/latest/
- 🤖 https://flask-session.readthedocs.io/en/latest/
- 📥 https://uwsgi-docs.readthedocs.io/en/latest/Configuration.html — long, multi-section; better to download
- 📥 https://alembic.sqlalchemy.org/en/latest/tutorial.html — key details spread across wider docs; grab the full single-page build if available

🤖 = fetchable via WebFetch. 📥 = download and paste in.

---

## Flask-Session + SQLAlchemy 2.0

- **`Table.create(bind=engine)` is a silent no-op** in SQLAlchemy 2.0. Use `db.metadata.create_all(conn)` inside a `with engine.begin() as conn:` block after `Session(app)` to actually create the session table.
- **Actual table name is `sessions`**, not `flask_sessions`. Any raw SQL must use `sessions`.
- Flask-Session's `create_all` runs even during `flask db upgrade`, which causes Alembic's initial migration to fail with "table already exists".

## Alembic / Flask-Migrate

- **Use `db stamp head` on first deploy**, not `db upgrade`. Flask-Session creates the tables automatically on app startup, so by the time Alembic runs, the tables already exist. `stamp head` records the current state without trying to re-create anything.
- **`db upgrade` is safe to re-run** — it's a no-op if already at head. Use it for all subsequent deploys.
- **`alembic_version` table not existing** means "untracked", not "empty database". Running `db upgrade` on an untracked but populated DB will fail. Check for the table first.
- Auto-migrate pattern: in `wsgi.py`, after `create_app()`, check if `alembic_version` exists in `inspect(db.engine).get_table_names()`. If not, call `stamp()`; otherwise call `upgrade()`. This makes migrations fully automatic on every restart.

## General Flask

- Use `127.0.0.1` not `localhost` for local dev on macOS — `localhost` can be intercepted by AirPlay Receiver on port 5000.
- Suppress background coordinators with a custom env var (e.g. `MY_APP_CLI`), not `FLASK_RUN_FROM_CLI` — the latter is not reliably set in all contexts.
