# The bastion's control plane (services/control): the fleet page, the Telegram mini app, booting
# and shutting down the game servers. deploy/bastion/docker-compose.yml runs it
FROM python:3.13-slim
# wg: the game servers' WireGuard peers; ssh: stopping and updating them
RUN apt-get update \
 && apt-get install -y --no-install-recommends wireguard-tools openssh-client \
 && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.30 /uv /bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1 PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations migrations
COPY control control
ENV PATH=/app/.venv/bin:$PATH CONTROL_DATA_DIR=/data
VOLUME /data
CMD ["python", "-m", "control"]
