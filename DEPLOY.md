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

The included `render.yaml` is configured for Render's free web service tier, so
you can get a public URL without adding a payment plan first. On the free tier,
the app's SQLite database is temporary: user/account/queue data can be lost when
the service restarts or redeploys.

For real use, hosted deployment should store data outside the app folder. This
project supports:

```text
QUEUEBOT_DB_PATH=/data/queue.db
```

On a paid Render web service, you can add a persistent disk and set:

```yaml
envVars:
  - key: QUEUEBOT_DB_PATH
    value: /data/queue.db
disk:
  name: queue-data
  mountPath: /data
  sizeGB: 1
```

For a stronger production setup, move from SQLite to PostgreSQL.

## Production Notes

- Use HTTPS only. Render and similar platforms provide HTTPS on their generated URLs.
- Do not run Uvicorn with `--reload` in production.
- Add real SMS/WhatsApp/email notifications before using this with live customers.
- Add backups, monitoring, session expiry, password reset, and rate limiting before
  relying on it for a business-critical queue.
