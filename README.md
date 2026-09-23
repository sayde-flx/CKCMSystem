# CKCM Sports System — Railway deployment

## Deploy steps
1. Push this folder (with `HTML/` and `static/` folders alongside `system.py`) to a GitHub repo.
2. In Railway: **New Project → Deploy from GitHub repo**.
3. Railway auto-detects Python via Nixpacks and uses the `Procfile` to start the app with gunicorn.
4. In the service's **Variables** tab, set:
   - `SECRET_KEY` — any long random string (e.g. `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `ADMIN_USERNAME` — e.g. `admin_zaide`
   - `ADMIN_PASSWORD` — a real password (6+ characters)
   - `FLASK_DEBUG` — leave unset or `false` in production
5. Railway sets `PORT` automatically — the app already reads it.
6. Deploy. Railway gives you a public URL under Settings → Networking → Generate Domain.

## ⚠️ Data is not persistent
This app keeps all users, players, and announcements in plain Python lists in
memory (`CKCMSportsSystem`). There is no database. That means:

- **Every redeploy wipes all data.** Restarting the service, pushing new code,
  or Railway restarting the container for any reason resets everything back
  to just the admin account.
- **Do not scale past 1 replica / 1 worker.** The `Procfile` is pinned to
  `--workers 1` on purpose — with more than one worker process, each one
  would have its own separate copy of the data, so a user could register on
  one worker and "not exist" on the next request if it lands on a different
  worker.

This is fine for a demo, a short-lived event sign-up, or local testing, but
**not** suitable for anything where losing registrations would be a problem.
To fix this properly, the `CKCMSportsSystem` class needs to be backed by a
real database (SQLite file on a Railway volume, or Postgres via Railway's
managed Postgres plugin). Ask if you'd like that migration done — it's a
different scope of change from just "making it deployable."

## Local run
```bash
pip install -r requirements.txt
export SECRET_KEY=dev-secret
export ADMIN_USERNAME=admin_zaide
export ADMIN_PASSWORD=changeme123
python system.py
```
