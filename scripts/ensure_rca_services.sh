#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${RCA_ROOT_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

FRONTEND_PORT="${RCA_FRONTEND_PORT:-3100}"
BACKEND_PORT="${RCA_BACKEND_PORT:-8100}"
FRONTEND_SCREEN="${RCA_FRONTEND_SCREEN:-rca-frontend-3100}"
BACKEND_SCREEN="${RCA_BACKEND_SCREEN:-rca-backend-8100}"
RECLAIM_PORTS="${RCA_RECLAIM_PORTS:-1}"

log() {
  printf '[rca-ensure] %s\n' "$*"
}

listener_pids() {
  local port="$1"
  lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true
}

pid_cwd() {
  local pid="$1"
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -n 1
}

pid_cmd() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null || true
}

is_frontend_pid() {
  local pid="$1"
  local cwd cmd
  cwd="$(pid_cwd "$pid")"
  cmd="$(pid_cmd "$pid")"
  case "$cwd" in
    "$FRONTEND_DIR"|"$FRONTEND_DIR"/*)
      [[ "$cmd" == *"next"* || "$cmd" == *"node"* ]]
      return
      ;;
  esac
  return 1
}

is_backend_pid() {
  local pid="$1"
  local cwd cmd
  cwd="$(pid_cwd "$pid")"
  cmd="$(pid_cmd "$pid")"
  case "$cwd" in
    "$BACKEND_DIR"|"$BACKEND_DIR"/*)
      [[ "$cmd" == *"uvicorn app.main:app"* ]]
      return
      ;;
  esac
  return 1
}

is_expected_pid() {
  local role="$1"
  local pid="$2"
  if [[ "$role" == "frontend" ]]; then
    is_frontend_pid "$pid"
  else
    is_backend_pid "$pid"
  fi
}

describe_pid() {
  local pid="$1"
  printf 'pid=%s cwd=%s cmd=%s' "$pid" "$(pid_cwd "$pid")" "$(pid_cmd "$pid")"
}

kill_pid() {
  local pid="$1"
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    if ! kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    sleep 0.4
  done
  kill -9 "$pid" 2>/dev/null || true
}

ensure_port_available_or_owned() {
  local role="$1"
  local port="$2"
  local unexpected=()
  local expected=()
  local pid

  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if is_expected_pid "$role" "$pid"; then
      expected+=("$pid")
    else
      unexpected+=("$pid")
    fi
  done < <(listener_pids "$port")

  if (( ${#unexpected[@]} )); then
    for pid in "${unexpected[@]}"; do
      log "port $port is occupied by a non-RCA process: $(describe_pid "$pid")"
      if [[ "$RECLAIM_PORTS" != "1" ]]; then
        log "RCA_RECLAIM_PORTS is not 1; refusing to stop non-RCA process"
        exit 1
      fi
      log "stopping non-RCA process on port $port"
      kill_pid "$pid"
    done
  fi

  expected=()
  while IFS= read -r pid; do
    [[ -z "$pid" ]] && continue
    if is_expected_pid "$role" "$pid"; then
      expected+=("$pid")
    else
      log "port $port is still occupied by an unexpected process: $(describe_pid "$pid")"
      exit 1
    fi
  done < <(listener_pids "$port")

  if (( ${#expected[@]} )); then
    log "$role already owns port $port (${expected[*]})"
    return 0
  fi
  return 1
}

start_backend() {
  log "starting backend on 127.0.0.1:$BACKEND_PORT"
  screen -S "$BACKEND_SCREEN" -X quit >/dev/null 2>&1 || true
  screen -dmS "$BACKEND_SCREEN" zsh -lc "cd \"$BACKEND_DIR\" && DATABASE_URL=\"sqlite+pysqlite:///./rca_workbench.db\" OBJECT_STORE_MODE=local LOCAL_ARTIFACT_ROOT=\"../.artifacts\" ./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $BACKEND_PORT"
}

start_frontend() {
  log "starting frontend on 127.0.0.1:$FRONTEND_PORT"
  screen -S "$FRONTEND_SCREEN" -X quit >/dev/null 2>&1 || true
  screen -dmS "$FRONTEND_SCREEN" zsh -lc "cd \"$FRONTEND_DIR\" && NEXT_PUBLIC_API_BASE_URL=\"http://127.0.0.1:$BACKEND_PORT/api\" pnpm exec next dev -H 127.0.0.1 -p $FRONTEND_PORT"
}

wait_for_http() {
  local url="$1"
  local label="$2"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      log "$label is reachable: $url"
      return 0
    fi
    sleep 1
  done
  log "$label did not become reachable: $url"
  return 1
}

main() {
  if ! ensure_port_available_or_owned backend "$BACKEND_PORT"; then
    start_backend
  fi
  wait_for_http "http://127.0.0.1:$BACKEND_PORT/api/health" "backend"

  if ! ensure_port_available_or_owned frontend "$FRONTEND_PORT"; then
    start_frontend
  fi
  wait_for_http "http://127.0.0.1:$FRONTEND_PORT/" "frontend"

  log "RCA services are ready"
  log "frontend: http://127.0.0.1:$FRONTEND_PORT"
  log "backend:  http://127.0.0.1:$BACKEND_PORT/api"
}

main "$@"
