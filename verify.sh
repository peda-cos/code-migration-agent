#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

uv sync --frozen --group dev
uv run --frozen mypy
uv run --frozen pytest -q
