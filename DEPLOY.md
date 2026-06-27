# Deploying Smart Queue Bot

You do not need a custom domain to deploy. A hosting platform can give the app
a public URL first, for example:

```text
https://gbemibot.onrender.com
```

The app is prepared for Docker-based hosting and reads the port from `PORT`.

## Recommended First Deployment: Render

1. Create a GitHub repository and push this project.
2. Create a Render account.
3. Choose **New** -> **Blueprint**.
4. Connect the GitHub repository.
5. Render will read `render.yaml` and create the web service.
6. After deploy, open the generated Render URL.

## Data Persistence

Local development stores data at:

```text
backend/queue.db
```

Hosted deployment should store data outside the app folder. This project supports:

```text
QUEUEBOT_DB_PATH=/data/queue.db
```

The included `render.yaml` mounts `/data` as a persistent disk. If your hosting
plan does not support persistent disks, the app can still start, but user data may
be lost when the server restarts or redeploys.

For a stronger production setup, move from SQLite to PostgreSQL.

## Production Notes

- Use HTTPS only. Render and similar platforms provide HTTPS on their generated URLs.
- Do not run Uvicorn with `--reload` in production.
- Add real SMS/WhatsApp/email notifications before using this with live customers.
- Add backups, monitoring, session expiry, password reset, and rate limiting before
  relying on it for a business-critical queue.

