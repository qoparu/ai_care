FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY backend/requirements.txt /srv/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend /srv/backend
COPY bot /srv/bot
COPY tools /srv/tools

# Run as a non-root user; this container handles personal health data.
RUN useradd --create-home --uid 10001 app && chown -R app:app /srv
USER app

WORKDIR /srv/backend
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
