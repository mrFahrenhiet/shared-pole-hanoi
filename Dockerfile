FROM ghcr.io/astral-sh/uv:latest@sha256:cdc6093146eb3ff6a40107b38f008b789e050e77ad87865e381d9917da55a168 AS uv
FROM python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83 AS base
COPY --from=uv /uv /uvx /usr/local/bin/
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

FROM base AS builder
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

FROM base AS runtime
COPY --from=builder /app/.venv /app/.venv
COPY pyproject.toml uv.lock ./
COPY app ./app
ENTRYPOINT ["uv", "run", "--locked", "--no-sync", "python", "-m", "app"]
CMD ["--help"]

FROM runtime AS test
RUN uv sync --locked
COPY tests ./tests
COPY examples ./examples
ENTRYPOINT ["uv", "run", "--locked", "--no-sync", "python", "-m", "pytest"]
