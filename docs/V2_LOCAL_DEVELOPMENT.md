# V2 Local Development

## Prerequisites

- Python 3.12 (the repository `.venv` is authoritative)
- Node.js and npm
- optional provider keys in the API process environment

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

Open **Settings** in the dashboard to add a hosted-provider key for the current API
session, test a supported endpoint, discover models, or run an isolated tool-call
format probe. Session keys override environment variables and disappear when the API
stops. They are not stored in SQLite or browser storage.

For Ollama, start the local daemon before using **Test connection**. Installed models
come from `/api/tags`. The page can copy an `ollama pull <model>` command, but model
downloads remain an explicit CLI operation.

Override ports with `-DashboardPort` / `-ApiPort` or
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
