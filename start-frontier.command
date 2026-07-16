#!/usr/bin/env bash

set -u

ROOT="$(cd "$(dirname "$0")" && pwd)"
"$ROOT/scripts/start_frontier.sh" "$@"
status=$?

if [[ -t 0 ]]; then
  printf '\nPress Return to close this window. The started services will keep running.\n'
  read -r _
fi

exit "$status"
