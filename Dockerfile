FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so edits to the source do not invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Stamped on every build so a client can tell which build it is talking to.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

COPY src/ ./src/
COPY webapp/ ./webapp/
COPY service/ ./service/
COPY scripts/ ./scripts/
COPY main.py ./

RUN uv sync --frozen --no-dev \
    && mkdir -p /app/data \
    && useradd --create-home --uid 10001 shelfplan \
    && chown -R shelfplan:shelfplan /app
USER shelfplan

VOLUME ["/app/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"

# --proxy-headers makes uvicorn rewrite the client address and scheme from
# X-Forwarded-*, which is what lets the app see "https" behind Fly or Caddy and
# lets the rate limiter see the real caller instead of the proxy. Only safe
# because nothing but the proxy can reach this port.
CMD ["uvicorn", "webapp.app:app",      "--host", "0.0.0.0", "--port", "8000",      "--proxy-headers", "--forwarded-allow-ips", "*"]
