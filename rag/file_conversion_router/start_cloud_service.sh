#!/usr/bin/env bash
set -euo pipefail

# Run on 128.32.43.46 after SSH login; PDF and video share POST /convert.
# Usage from the repository root:
#   bash rag/file_conversion_router/start_cloud_service.sh
readonly CONVERSION_PUBLIC_HOST="128.32.43.46"
readonly CONVERSION_PORT="8010"

# Resolve imports, Poetry configuration, and .env from rag/ regardless of cwd.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v poetry >/dev/null 2>&1; then
    printf 'Poetry is required. Install it and configure the RAG environment first.\n' >&2
    exit 1
fi

# Match the existing launcher: no local OpenTelemetry collector is required.
export OTEL_SDK_DISABLED=true
export OTEL_METRICS_EXPORTER=none
export OTEL_TRACES_EXPORTER=none
export OTEL_LOGS_EXPORTER=none

# WhisperX needs the CUDA libraries installed in the selected Python environment.
# Discover them using Poetry's Python, not the system Python.
CONVERSION_NVIDIA_LIBS="$(poetry run python - <<'PY'
import sys
from pathlib import Path

paths = [
    str(path)
    for root in sys.path if root
    for path in sorted((Path(root) / "nvidia").glob("*/lib"))
    if path.is_dir()
]
print(":".join(dict.fromkeys(paths)))
PY
)"
if [[ -n "$CONVERSION_NVIDIA_LIBS" ]]; then
    export LD_LIBRARY_PATH="${CONVERSION_NVIDIA_LIBS}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
fi

# The semaphore in conversion_api is per process: keep exactly one worker.
CONVERSION_COMMAND=(poetry run python -m uvicorn
    file_conversion_router.conversion_api:app
    --host 0.0.0.0 --port "$CONVERSION_PORT" --workers 1)
if [[ -f .env ]]; then
    CONVERSION_COMMAND+=(--env-file .env)
fi

printf 'Starting PDF and video conversion service on 0.0.0.0:%s\n' "$CONVERSION_PORT"
printf 'Public endpoint: http://%s:%s/convert\n' "$CONVERSION_PUBLIC_HOST" "$CONVERSION_PORT"
printf 'API docs:        http://%s:%s/docs\n' "$CONVERSION_PUBLIC_HOST" "$CONVERSION_PORT"

# Forward signals and the server exit status directly to the calling shell.
exec "${CONVERSION_COMMAND[@]}"
