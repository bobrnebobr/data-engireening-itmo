FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.10.11 /uv /bin/uv

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    DUCKDB_EXTENSION_DIRECTORY=/opt/duckdb/extensions \
    PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
RUN python -c 'import duckdb, os; duckdb.connect(config={"extension_directory": os.environ["DUCKDB_EXTENSION_DIRECTORY"]}).install_extension("httpfs")'

COPY app/ ./app/
COPY duckdb_analysis/ ./duckdb_analysis/
COPY config/ ./config/

RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD ["python", "-m", "app.main"]
