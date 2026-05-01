#!/usr/bin/env bash
set -euo pipefail

# Start the file-conversion FastAPI service.
# Usage:  ./start_conversion_api.sh [host] [port]

cd "$(dirname "$0")"

HOST="${1:-0.0.0.0}"
PORT="${2:-8010}"

# Silence transformers' auto-initialized OpenTelemetry exporter
# (it tries to push metrics/traces to http://localhost:4318 which isn't running).
export OTEL_SDK_DISABLED=true
export OTEL_METRICS_EXPORTER=none
export OTEL_TRACES_EXPORTER=none
export OTEL_LOGS_EXPORTER=none

exec poetry run uvicorn file_conversion_router.conversion_api:app \
    --host "$HOST" --port "$PORT"
