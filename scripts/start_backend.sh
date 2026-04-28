#!/bin/bash

set -u

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-9178}"

resolve_python() {
  if [ -x "${ROOT_DIR}/.venv/bin/python" ]; then
    printf '%s\n' "${ROOT_DIR}/.venv/bin/python"
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi

  return 1
}

PYTHON_BIN="$(resolve_python)"
if [ -z "${PYTHON_BIN:-}" ]; then
  printf '[backend] Python 3 was not found. Create .venv or install python3 first.\n' >&2
  exit 1
fi

cd "${ROOT_DIR}" || exit 1
exec "${PYTHON_BIN}" -m uvicorn backend.main:app \
  --reload \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --app-dir "${ROOT_DIR}" \
  --reload-dir "${ROOT_DIR}"
