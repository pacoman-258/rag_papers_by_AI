#!/bin/bash

set -u

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_HOST="127.0.0.1"
BACKEND_PORT="9178"
FRONTEND_HOST="127.0.0.1"
FRONTEND_PORT="5173"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
RUNTIME_DIR="$(mktemp -d "${TMPDIR:-/tmp}/rag-papers-workbench.XXXXXX")"
BACKEND_LOG="${RUNTIME_DIR}/backend.log"
FRONTEND_LOG="${RUNTIME_DIR}/frontend.log"
BACKEND_PID=""
FRONTEND_PID=""
TAIL_PID=""

print_line() {
  printf '%s\n' "$1"
}

fail() {
  print_line ""
  print_line "[startup] $1"
  exit 1
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Missing required command: $1"
  fi
}

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

check_python_module() {
  local python_bin="$1"
  local module_name="$2"
  if ! "$python_bin" -c "import ${module_name}" >/dev/null 2>&1; then
    fail "Python module '${module_name}' is not available in ${python_bin}"
  fi
}

check_port_free() {
  local port="$1"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    print_line "[startup] Port ${port} is already in use:"
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN
    fail "Please stop the process above or change the port before starting the workbench."
  fi
}

wait_for_http() {
  local name="$1"
  local url="$2"
  local timeout_seconds="$3"
  local attempt=0

  while [ "${attempt}" -lt "${timeout_seconds}" ]; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done

  print_line "[startup] ${name} did not become ready within ${timeout_seconds}s."
  return 1
}

cleanup() {
  if [ -n "${TAIL_PID}" ] && kill -0 "${TAIL_PID}" >/dev/null 2>&1; then
    kill "${TAIL_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${BACKEND_PID}" ] && kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    kill "${BACKEND_PID}" >/dev/null 2>&1 || true
  fi
  if [ -n "${FRONTEND_PID}" ] && kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    kill "${FRONTEND_PID}" >/dev/null 2>&1 || true
  fi
}

trap 'cleanup' EXIT INT TERM

require_command "curl"
require_command "lsof"
require_command "npm"

PYTHON_BIN="$(resolve_python)" || fail "Python 3 was not found. Create .venv or install python3 first."
check_python_module "${PYTHON_BIN}" "uvicorn"

if [ ! -d "${ROOT_DIR}/frontend/node_modules" ]; then
  fail "frontend/node_modules is missing. Run 'cd frontend && npm install' first."
fi

check_port_free "${BACKEND_PORT}"
check_port_free "${FRONTEND_PORT}"

print_line "[startup] Logs will be written to:"
print_line "[startup]   backend: ${BACKEND_LOG}"
print_line "[startup]   frontend: ${FRONTEND_LOG}"

print_line "[startup] Starting backend on ${BACKEND_URL} ..."
(
  cd "${ROOT_DIR}" &&
    BACKEND_HOST="${BACKEND_HOST}" BACKEND_PORT="${BACKEND_PORT}" "${ROOT_DIR}/scripts/start_backend.sh"
) >"${BACKEND_LOG}" 2>&1 &
BACKEND_PID="$!"

print_line "[startup] Starting frontend on ${FRONTEND_URL} ..."
(
  cd "${ROOT_DIR}/frontend" &&
    npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}" --strictPort
) >"${FRONTEND_LOG}" 2>&1 &
FRONTEND_PID="$!"

tail -n +1 -f "${BACKEND_LOG}" "${FRONTEND_LOG}" &
TAIL_PID="$!"

if ! wait_for_http "backend" "${BACKEND_URL}/api/config" 60; then
  print_line "[startup] Backend log tail:"
  tail -n 40 "${BACKEND_LOG}" || true
  exit 1
fi

if ! wait_for_http "frontend" "${FRONTEND_URL}" 60; then
  print_line "[startup] Frontend log tail:"
  tail -n 40 "${FRONTEND_LOG}" || true
  exit 1
fi

print_line "[startup] Workbench is ready."
print_line "[startup] Opening browser at ${FRONTEND_URL}"
open "${FRONTEND_URL}"

while true; do
  if ! kill -0 "${BACKEND_PID}" >/dev/null 2>&1; then
    print_line "[startup] Backend process exited."
    tail -n 40 "${BACKEND_LOG}" || true
    exit 1
  fi
  if ! kill -0 "${FRONTEND_PID}" >/dev/null 2>&1; then
    print_line "[startup] Frontend process exited."
    tail -n 40 "${FRONTEND_LOG}" || true
    exit 1
  fi
  sleep 1
done
