# syntax=docker/dockerfile:1
# One image for every atp service; the command picks the role (atp run <service>).
# Built for linux/arm64 in CI (ECS on Graviton) and natively for local dev.
FROM mirror.gcr.io/library/python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# Optional extra CA (corporate/sandbox TLS proxies): --secret id=extra_ca,src=/path/ca.crt
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-editable

FROM mirror.gcr.io/library/python:3.12-slim
RUN useradd --create-home atp
WORKDIR /app
COPY --from=build /app /app
COPY alembic.ini ./
COPY agents ./agents
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER atp
CMD ["atp", "--help"]
