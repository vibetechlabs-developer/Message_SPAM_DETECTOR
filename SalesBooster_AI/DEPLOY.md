# SalesBooster AI — deployment

Stack: **Django REST API** (`django_backend`) + **React/Vite** (`frontend`). Audits can call **Node + Playwright** from the API host (`frontend/scripts/browserAudit.mjs`); for full audits in Docker, extend the backend image with Node or run audits on a worker.

## 1. Python dependencies

```bash
cd django_backend
python -m venv .venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate   # Linux/macOS
pip install -r requirements.txt
```

## 2. Environment

```bash
cp .env.example .env
# Edit .env: DJANGO_SECRET_KEY, DJANGO_ALLOWED_HOSTS, DJANGO_CORS_ALLOWED_ORIGINS, SMTP_*
```

## 3. Database and static files

```bash
python manage.py migrate
python manage.py collectstatic --noinput
```

## 4. Run API (production-style)

```bash
gunicorn server.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 120
```

On **Heroku**, set `PORT` and use the included `Procfile` + `runtime.txt`.

## 5. Frontend build

Point the SPA at your API (same host + reverse proxy, or absolute API URL):

```bash
cd frontend
npm ci
# Optional: echo VITE_API_BASE_URL=https://api.yourdomain.com > .env.production
npm run build
```

Serve `frontend/dist` with **nginx** (see `frontend/nginx.default.conf`) and proxy `/api` to Gunicorn.

## 6. Docker Compose (monolith-style)

From `SalesBooster_AI`:

1. Create `django_backend/.env` from `.env.example` (Compose loads it).
2. Run:

```bash
docker compose up --build
```

- UI: `http://localhost:8080`
- Health: `http://localhost:8080/api/health`

SQLite data persists in the `sqlite_data` volume (`DJANGO_SQLITE_PATH=/data/db.sqlite3`).

## 7. Demo leads (optional)

```bash
cd django_backend
python manage.py seed_demo_leads --username YOUR_USER --count 5
```
