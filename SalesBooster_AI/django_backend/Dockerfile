# SalesBooster Django API
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=server.settings

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN DJANGO_SECRET_KEY=collect-static-only python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "server.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120"]
