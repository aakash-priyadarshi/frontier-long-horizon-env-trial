# V2 Local Development

## Prerequisites

- Python 3.12 (the repository `.venv` is authoritative)
- Node.js and npm
- optional provider keys in the API process environment

## One-click setup and startup

Use `start-frontier.cmd` on Windows or `start-frontier.command` on macOS. The native
wrapper calls `scripts/start_frontier.ps1` or `scripts/start_frontier.sh` and:

1. checks Git, Python 3.12, Node.js 20.9 or newer, and npm;
2. uses Winget (Windows) or Homebrew (macOS) to install a missing required system
   dependency, with the package manager's normal prompts;
3. creates `.venv`, installs `.[test,adapters]`, and runs deterministic `npm ci` when
   the corresponding dependency lock has changed;
4. starts and health-checks the API and dashboard, reusing a healthy existing service;
5. detects optional Ollama, starts it when possible, reports local-model availability,
   and opens `http://localhost:3000`.

Ollama is deliberately not auto-installed, and the launcher never pulls a model.
Without Ollama, scripted and hosted-provider features still work. With Ollama, open
**Settings -> Tool compatibility** to discover installed models and test each exact
model digest. Runtime PID, dependency-stamp, and log files live under the gitignored
`.frontier/` directory. The launchers bind services to `127.0.0.1`; the browser uses
the intentional `http://localhost:<port>` dashboard origin.

If macOS removes executable permission while unpacking an archive, run
`chmod +x start-frontier.command scripts/start_frontier.sh` once. The first setup
requires a network connection and may request administrator approval. Pass
`-NoBrowser` to the PowerShell script or `--no-browser` to the Bash script to skip
opening the browser.

## Manual developer setup

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[test,adapters]"
cd apps\dashboard
npm install
cd ..\..
.\scripts\dev_v2.ps1
```

Defaults:

- Dashboard: `http://localhost:3000`
- API: `http://localhost:8000`

`dev_v2.ps1` configures `http://localhost:<dashboard-port>` as the dashboard
origin. The API intentionally permits that exact origin and its
`http://127.0.0.1:<dashboard-port>` loopback alias. It does not use a wildcard
credential origin.

Open **Settings** in the dashboard to add a hosted-provider key, test a supported
endpoint, discover models, or run an isolated tool-call format probe. Session-only
keys are the default and disappear when the API stops. Select **Save to local .env**
to explicitly persist a plaintext key in the gitignored repository `.env`; it reloads
on API startup and can be removed from Settings. Precedence is session, local `.env`,
process environment, then missing. Keys are not stored in SQLite or browser storage.
Discovered model metadata and endpoint/digest-bound probe verdicts reload from the
credential-free `.frontier/provider-state.json` cache.

For Ollama, start the local daemon before using **Test connection**. Installed models
come from `/api/tags`. The page can copy an `ollama pull <model>` command, but model
downloads remain an explicit CLI operation.

The manual `dev_v2.ps1` launcher overrides ports with `-DashboardPort` / `-ApiPort` or
`FRONTIER_DASHBOARD_PORT` / `FRONTIER_API_PORT`. The script fails clearly when a
port is occupied and stops both child processes on interruption.

Two-terminal alternative:

```powershell
# terminal 1
.\.venv\Scripts\python.exe -m uvicorn evaluation_service.app:app --reload --port 8000

# terminal 2
cd apps\dashboard
$env:NEXT_PUBLIC_FRONTIER_API_URL="http://localhost:8000"
npm run dev
```

## CLI

```powershell
.\.venv\Scripts\python.exe -m model_eval providers
.\.venv\Scripts\python.exe -m model_eval run --provider scripted --model scripted-valid --split eval --seed 0 --attempts 1
.\.venv\Scripts\python.exe -m model_eval run --provider openai-compatible --model <model-name> --split eval --seed-start 0 --seed-count 5 --attempts 2
.\.venv\Scripts\python.exe -m model_eval compare --batch <batch-id>
```

## Verification

```powershell
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/v2 -q
.\.venv\Scripts\python.exe -m pytest tests/v2 -q
.\.venv\Scripts\python.exe -m pytest tests -q
cd apps\dashboard
npm run lint
npm run typecheck
npm run test
npm run build
npm run test:e2e
```

Local state is under `.frontier/` and is gitignored. Delete or redirect it only when
you intentionally want a clean local history. The scripted provider never requires
paid APIs or seeded fake dashboard results; it runs the real environment and strict
verifier.

New episodes retain a sanitized candidate diff under `.frontier/runs/<run_id>/`.
Open **Runs** to see total candidate-diff storage, delete all retained diffs, or open
an episode to delete only its diff or the complete terminal episode. Diff cleanup
preserves scores, timelines, changed-file summaries, and artifact digests. Historical
episodes created before this feature continue to show their existing file summary
but cannot reconstruct source that was never retained.

## Browser and visual checks

Use a current Chrome, Edge, Firefox, or Safari release. The Playwright suite uses
Chromium and exercises the dashboard load, scripted launch, live batch result, run
timeline, comparison charts and tables, mobile navigation, reduced motion, and
session and opt-in local credential flows. For a manual polish check, inspect widths 1440, 1024,
768, and 390 pixels in both themes, then emulate reduced motion. Confirm that the
browser console has no React or Chart.js errors.

All comparison charts have an **Accessible data table** disclosure and CSV export;
the comparison toolbar can replace all canvases with tables. Theme choice and safe
recent model identifiers may be stored in `localStorage`; provider credentials are
never stored there or in `sessionStorage`.
