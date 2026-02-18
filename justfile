set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

api_host := env_var_or_default('API_HOST', '127.0.0.1')
api_port := env_var_or_default('API_PORT', '8000')
client_port := env_var_or_default('CLIENT_PORT', '8080')
uv_cache_dir := env_var_or_default('UV_CACHE_DIR', '.uv-cache')

bootstrap:
    if command -v uv >/dev/null 2>&1; then
      UV_CACHE_DIR={{uv_cache_dir}} uv sync --dev
    else
      python3 -m venv .venv
      .venv/bin/pip install -e ".[dev]"
    fi
    mkdir -p data
    just db-upgrade
    just seed

dev:
    just db-upgrade
    (python3 -m http.server {{client_port}} --directory client >/tmp/triagedeck-client.log 2>&1 &) ; \
    (UV_CACHE_DIR={{uv_cache_dir}} uv run python -m uvicorn fastapi_server.main:app --host {{api_host}} --port {{api_port}} --reload)

test:
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m pytest -q

test-api:
    @echo "[test-api] Core API tests"
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m pytest -q fastapi_server/tests/test_api.py
    @echo "[test-api] Live HTTP contract tests (socket/network required)"
    @echo "[test-api] If skipped, pytest will print the skip reason below."
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m pytest -q -rs fastapi_server/tests/test_http_contract.py

test-client:
    @echo "No automated client tests yet"

lint:
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m ruff check .

fmt:
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m ruff format .

check: fmt lint test

db-migrate:
    @echo "Alembic not wired yet; schema is managed in fastapi_server/db.py"

db-upgrade:
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m fastapi_server.db init

db-reset:
    rm -f data/triagedeck.db
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m fastapi_server.db init

seed:
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m scripts.seed

clean:
    rm -rf .pytest_cache .ruff_cache __pycache__ */__pycache__ fastapi_server/**/__pycache__

export-smoke:
    UV_CACHE_DIR={{uv_cache_dir}} uv run python -m scripts.export_smoke
