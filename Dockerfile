# XplagiaX Integrity — API image. Built from the pinned lock in requirements.txt.
# NOTE: not built in the Phase-1 session (no Docker daemon available). See docs/PERFORMANCE.md.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app
WORKDIR /srv

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini pyproject.toml ./
COPY integrity ./integrity

USER app
EXPOSE 8000

# Two sync workers by default; tune with measurements, not with CPU count.
# --max-requests recycles workers to bound slow memory growth.
ENV XI_ENV=production \
    GUNICORN_CMD_ARGS="--bind 0.0.0.0:8000 --workers 2 --threads 1 --timeout 30 --graceful-timeout 20 --max-requests 2000 --max-requests-jitter 200"

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/live', timeout=2).status==200 else 1)"

CMD ["gunicorn", "integrity.app:create_app()"]
