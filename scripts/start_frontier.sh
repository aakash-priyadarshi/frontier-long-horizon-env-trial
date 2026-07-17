#!/usr/bin/env bash

set -Eeuo pipefail

API_PORT="${FRONTIER_API_PORT:-8000}"
DASHBOARD_PORT="${FRONTIER_DASHBOARD_PORT:-3000}"
NO_BROWSER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-browser) NO_BROWSER=1 ;;
    *) printf '[ERROR] Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DASHBOARD="$ROOT/apps/dashboard"
RUNTIME="$ROOT/.frontier/launcher"
LOGS="$ROOT/.frontier/logs"
VENV="$ROOT/.venv"
VENV_PYTHON="$VENV/bin/python"
API_URL="http://localhost:$API_PORT"
DASHBOARD_URL="http://localhost:$DASHBOARD_PORT"
OLLAMA_URL="http://127.0.0.1:11434"

mkdir -p "$RUNTIME" "$LOGS"

if [[ -t 1 ]]; then
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi

info() { printf '%s[INFO]%s %s\n' "$CYAN" "$RESET" "$*"; }
ok() { printf '%s[OK]%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s[WARNING]%s %s\n' "$YELLOW" "$RESET" "$*"; }
fail() { printf '%s[ERROR]%s %s\n' "$RED" "$RESET" "$*" >&2; }
die() { fail "$*"; info "Runtime logs, when available: $LOGS"; exit 1; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  die "This launcher targets macOS. On Windows, double-click start-frontier.cmd."
fi

prepend_homebrew_path() {
  [[ -d /opt/homebrew/bin ]] && export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
  [[ -d /usr/local/bin ]] && export PATH="/usr/local/bin:$PATH"
}

ensure_homebrew() {
  prepend_homebrew_path
  if command -v brew >/dev/null 2>&1; then return; fi
  info "Homebrew is required to install missing prerequisites. Starting the official Homebrew installer; it may request your password."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  prepend_homebrew_path
  command -v brew >/dev/null 2>&1 || die "Homebrew installation did not make brew available. Follow the installer instructions, then run this launcher again."
}

python_is_312() {
  [[ -x "$1" ]] && [[ "$("$1" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)" == "3.12" ]]
}

node_is_supported() {
  command -v node >/dev/null 2>&1 || return 1
  local version major minor
  version="$(node --version 2>/dev/null | sed 's/^v//')"
  IFS=. read -r major minor _ <<<"$version"
  [[ "$major" =~ ^[0-9]+$ && "$minor" =~ ^[0-9]+$ ]] || return 1
  (( major > 20 || (major == 20 && minor >= 9) ))
}

install_or_upgrade_formula() {
  local formula="$1" label="$2"
  info "$label is missing or unsupported. Installing it with Homebrew."
  if brew list --versions "$formula" >/dev/null 2>&1; then
    brew upgrade "$formula" || true
  else
    brew install "$formula"
  fi
}

ensure_system_dependencies() {
  local needs_git=0 needs_python=0 needs_node=0
  command -v git >/dev/null 2>&1 || needs_git=1
  command -v python3.12 >/dev/null 2>&1 || needs_python=1
  node_is_supported || needs_node=1

  if (( needs_git || needs_python || needs_node )); then
    ensure_homebrew
    (( needs_git )) && install_or_upgrade_formula git "Git"
    (( needs_python )) && install_or_upgrade_formula python@3.12 "Python 3.12"
    (( needs_node )) && install_or_upgrade_formula node "Node.js 20.9 or newer"
    prepend_homebrew_path
    hash -r
  fi

  command -v git >/dev/null 2>&1 || die "Git is still unavailable after dependency setup."
  command -v python3.12 >/dev/null 2>&1 || die "Python 3.12 is still unavailable after dependency setup."
  node_is_supported || die "Node.js 20.9 or newer is still unavailable after dependency setup."
  command -v npm >/dev/null 2>&1 || die "npm is unavailable after Node.js setup."
}

file_digest() { shasum -a 256 "$1" | awk '{print $1}'; }
stamp_matches() { [[ -f "$1" ]] && [[ "$(tr -d '\r\n' < "$1")" == "$2" ]]; }
write_stamp() { printf '%s\n' "$2" > "$1"; }

install_project_dependencies() {
  if ! python_is_312 "$VENV_PYTHON"; then
    info "Creating the repository Python 3.12 environment."
    rm -rf "$VENV"
    python3.12 -m venv "$VENV"
  fi

  local python_digest python_stamp imports_ready=0
  python_digest="$(file_digest "$ROOT/pyproject.toml")"
  python_stamp="$RUNTIME/python-dependencies.sha256"
  "$VENV_PYTHON" -c 'import fastapi, gymnasium, httpx, pytest, uvicorn, yaml' >/dev/null 2>&1 && imports_ready=1
  if (( ! imports_ready )) || ! stamp_matches "$python_stamp" "$python_digest"; then
    info "Installing Frontier Python dependencies into .venv."
    "$VENV_PYTHON" -m pip install -e "$ROOT[test,adapters]"
    write_stamp "$python_stamp" "$python_digest"
  fi
  "$VENV_PYTHON" -m pip check >/dev/null || die "The Python environment contains incompatible dependencies."
  ok "Python 3.12 and project dependencies are ready."

  local lock_file node_digest node_stamp
  lock_file="$DASHBOARD/package-lock.json"
  [[ -f "$lock_file" ]] || die "Dashboard package-lock.json is missing."
  node_digest="$(file_digest "$lock_file")"
  node_stamp="$RUNTIME/dashboard-dependencies.sha256"
  if [[ ! -d "$DASHBOARD/node_modules" ]] || ! stamp_matches "$node_stamp" "$node_digest"; then
    info "Installing deterministic dashboard dependencies with npm ci."
    npm ci --prefix "$DASHBOARD"
    write_stamp "$node_stamp" "$node_digest"
  fi
  ok "Node.js, npm, and dashboard dependencies are ready."
}

web_ready() { curl --silent --show-error --fail --max-time 5 "$1" >/dev/null 2>&1; }
api_ready() { web_ready "http://127.0.0.1:$API_PORT/api/health"; }
dashboard_ready() { web_ready "http://127.0.0.1:$DASHBOARD_PORT"; }
ollama_ready() { web_ready "$OLLAMA_URL/api/tags"; }

wait_for() {
  local probe="$1" timeout="${2:-60}" started
  started=$SECONDS
  while (( SECONDS - started < timeout )); do
    "$probe" && return 0
    sleep 0.5
  done
  return 1
}

port_is_listening() {
  /usr/sbin/lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

start_ollama_if_available() {
  local ollama_bin=""
  if command -v ollama >/dev/null 2>&1; then
    ollama_bin="$(command -v ollama)"
  elif [[ -x /Applications/Ollama.app/Contents/Resources/ollama ]]; then
    ollama_bin=/Applications/Ollama.app/Contents/Resources/ollama
  elif [[ ! -d /Applications/Ollama.app ]]; then
    warn "Ollama is not installed. Hosted providers and scripted evaluations work, but local-model features will not. See Settings -> Tool compatibility for supported models and setup guidance."
    return
  fi

  if ! ollama_ready; then
    info "Ollama is installed; starting its local service."
    if [[ -d /Applications/Ollama.app ]]; then
      open -gj -a Ollama >/dev/null 2>&1 || true
      wait_for ollama_ready 15 || true
    fi
    if ! ollama_ready && [[ -n "$ollama_bin" ]]; then
      nohup "$ollama_bin" serve >"$LOGS/ollama.out.log" 2>"$LOGS/ollama.err.log" </dev/null &
      write_stamp "$RUNTIME/ollama.pid" "$!"
      wait_for ollama_ready 20 || true
    fi
  fi

  if ollama_ready; then
    ok "Ollama is installed and running. Local-model features will work. See Settings -> Tool compatibility for model details."
  else
    warn "Ollama is installed but its endpoint is not reachable. Open the Ollama app; local-model features will remain unavailable until it is running."
  fi
}

start_frontier_services() {
  export FRONTIER_DASHBOARD_ORIGIN="$DASHBOARD_URL"
  export NEXT_PUBLIC_FRONTIER_API_URL="$API_URL"

  if api_ready; then
    ok "Frontier API is already healthy at $API_URL."
  else
    port_is_listening "$API_PORT" && die "Port $API_PORT is occupied by something other than the expected Frontier API."
    info "Starting the Frontier API."
    (
      cd "$ROOT"
      nohup "$VENV_PYTHON" -m uvicorn evaluation_service.app:app --host 127.0.0.1 --port "$API_PORT" \
        >"$LOGS/api.out.log" 2>"$LOGS/api.err.log" </dev/null &
      write_stamp "$RUNTIME/api.pid" "$!"
    )
    wait_for api_ready 60 || die "Frontier API did not become healthy. Review .frontier/logs/api.err.log."
    ok "Frontier API is healthy at $API_URL."
  fi

  if dashboard_ready; then
    ok "Dashboard is already available at $DASHBOARD_URL."
  else
    port_is_listening "$DASHBOARD_PORT" && die "Port $DASHBOARD_PORT is occupied by something other than the expected Frontier dashboard."
    info "Starting the Frontier dashboard."
    (
      cd "$DASHBOARD"
      nohup npm run dev -- --hostname 127.0.0.1 --port "$DASHBOARD_PORT" \
        >"$LOGS/dashboard.out.log" 2>"$LOGS/dashboard.err.log" </dev/null &
      write_stamp "$RUNTIME/dashboard.pid" "$!"
    )
    wait_for dashboard_ready 60 || die "Frontier dashboard did not become ready. Review .frontier/logs/dashboard.err.log."
    ok "Dashboard is ready at $DASHBOARD_URL."
  fi
}

printf '\nFrontier one-click launcher\n'
printf 'Repository: %s\n' "$ROOT"
ensure_system_dependencies
install_project_dependencies
start_ollama_if_available
start_frontier_services
printf '\n'
ok "Frontier is ready: $DASHBOARD_URL"
info "API docs: $API_URL/docs"
info "Runtime logs: $LOGS"

if (( ! NO_BROWSER )); then open "$DASHBOARD_URL"; fi
