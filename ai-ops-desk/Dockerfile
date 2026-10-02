# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Build stage: resolve dependencies into a venv.
#
# requirements.txt installs galileo and the six agent-control-* packages
# straight from public GitHub repos, so this stage needs `git` and outbound
# network access. Keeping it separate means git and the compilers never ship
# in the runtime image.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

RUN apt-get update \
 && apt-get install -y --no-install-recommends git build-essential \
 && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /tmp/build
COPY requirements.lock ./

# --no-deps is deliberate, not an optimisation: agent-control-evaluators (pulled
# in by agent-control-sdk and -engine) requires `sqlglot[c]<29.1.0`, and every
# 29.x release of the sqlglotc accelerator has been removed from PyPI, so any
# resolution of requirements.txt now fails outright. requirements.lock pins the
# full known-good closure instead. See that file for the details.
RUN pip install --upgrade pip \
 && pip install --no-deps -r requirements.lock


# ---------------------------------------------------------------------------
# Runtime stage.
# ---------------------------------------------------------------------------
FROM python:3.12-slim

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # The Ops drawer's live-target pin is persisted here. /data is a writable
    # mount (emptyDir in Kubernetes) because the app root is owned by root.
    PROMO_DEMO_STATE_FILE=/data/.galileo_active_target.json

COPY --from=build /opt/venv /opt/venv

WORKDIR /app
COPY . .

# Run unprivileged. /data must be writable by the app user for the live-target
# state file; the rest of /app stays read-only to the process.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin appuser \
 && mkdir -p /data \
 && chown -R appuser:appuser /data

USER appuser

EXPOSE 8000

# No --reload: this is a long-lived server, and the reloader's extra process
# would break the in-process state the Ops endpoints rely on.
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
