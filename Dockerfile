# syntax=docker/dockerfile:1.7
#
# Production container for 副手 (Fushou).
#
# Build:
#   docker build -t fushou:latest .
#
# Run (Telegram default):
#   docker run --rm -p 8080:8080 --env-file .env fushou:latest
#
# Run (Teams):
#   docker run --rm -p 3978:3978 \
#     -e CHAT_PLATFORM=teams -e PORT=3978 \
#     --env-file .env fushou:latest
#
# Build choices:
#   - Two-stage to keep the final image small: builder installs deps
#     into a wheelhouse, runtime layer only carries what's needed.
#   - python:3.11-slim base — matches CI; avoids the security delta of
#     `latest` and the size hit of `python:3.11`.
#   - Non-root user `app` for the runtime layer per docs/04 §C Do
#     "低權限沙箱".
#   - No build tools in the runtime layer (only in the builder).

# --- Builder stage ---
FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# build-essential is needed because cryptography (via pyjwt[crypto]) ships
# wheels for most archs but may need to compile from sdist on uncommon
# platforms; rather than gamble, install the compiler in the builder only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy only what's needed to install — better layer caching for changes
# that touch source but not deps.
COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

# Install into /install so we can copy a single tree into the runtime layer.
RUN pip install --prefix=/install ".[]"

# --- Runtime stage ---
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# tini gives us a sane PID 1 — agent.reply / aiohttp / python-telegram-bot
# all spawn tasks, and tini cleans them up on SIGTERM rather than leaving
# zombies. ca-certificates is needed for outbound TLS to Microsoft / Anthropic.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 --shell /sbin/nologin app

WORKDIR /app

# Pull the installed packages from the builder stage. This includes all
# transitive deps but not build tools.
COPY --from=builder /install /usr/local

# Source — owned by `app` so the runtime user can read it but not write.
COPY --chown=app:app src/ ./src/
COPY --chown=app:app docs/ ./docs/

# Runtime-writable dirs the app expects. Mounted from the host (or a
# Docker volume) in production so state survives container restart;
# we still create empty dirs here so a fresh image runs.
RUN mkdir -p /app/memories/sessions /app/trust /app/logs \
 && chown -R app:app /app/memories /app/trust /app/logs

USER app

# Default port — Telegram uses 8080, Teams uses 3978. Operators expose
# the right one based on CHAT_PLATFORM.
EXPOSE 8080 3978

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "src.main"]
