# syntax=docker/dockerfile:1.7

# =============================================================================
# Stage 1 -- builder. Compilers and headers live here and are never shipped.
# =============================================================================
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependency metadata is copied on its own first. Application code changes on
# every commit; pyproject.toml does not, so this layer stays cached and a
# normal code change rebuilds in seconds instead of reinstalling every wheel.
COPY pyproject.toml README.md ./
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# The build toolchain is pinned so two builds of the same commit resolve the
# same pip/setuptools/wheel. The application's own dependencies are already
# constrained in pyproject.toml, which is the "requirements file" DL3013 asks
# for -- hence --no-cache-dir here and the targeted ignore in .hadolint.yaml.
RUN pip install --no-cache-dir \
        pip==26.2.1 \
        setuptools==84.0.0 \
        wheel==0.48.0 \
    && pip install --no-cache-dir .

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install --no-deps .

# =============================================================================
# Stage 2 -- runtime. No compilers, no pip cache, no source tree beyond what
# the process actually needs to run.
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOST=0.0.0.0 \
    APP_PORT=8000

# libpq5 is the only runtime OS dependency psycopg needs; the -dev package and
# gcc stayed behind in the builder.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# A fixed, non-root uid/gid. Fixed because Kubernetes runAsUser must match a
# number, and non-root because a container escape should not land on uid 0.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=root:root app ./app
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod 755 /usr/local/bin/entrypoint.sh

# Code is owned by root and readable-but-not-writable by the app user: the
# running process cannot rewrite its own source, which removes a whole class
# of post-exploitation persistence.
USER 10001:10001

EXPOSE 8000

# Points at the liveness endpoint on purpose -- it must not depend on the
# database, or Docker would mark a recoverable dependency outage as unhealthy.
# Exec form, not shell form. The trailing `|| exit 1` was redundant -- a
# non-zero exit from curl already marks the container unhealthy -- and it was
# the only thing that required a shell here.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["curl", "-fsS", "http://127.0.0.1:8000/health/live"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

LABEL org.opencontainers.image.title="devops-production-demo" \
      org.opencontainers.image.description="Reference production-shaped FastAPI service" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="https://github.com/rthway/devops-production-demo"
