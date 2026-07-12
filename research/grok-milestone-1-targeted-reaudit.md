# Milestone 1 targeted re-audit

**Role:** falsify-by-default closure review of accepted critical/major findings  
**Scope:** read-only; no implementation changes; no Milestone 2 work  
**Audited source:** `dd7e4acf36b6585735ec07045a9a25455eb51df2`  
**Audited receipt tip:** `42b007e0c6b39ea372c49e9e7c95a0e6a2a8b107`  
**Working tree:** `42b007e` (receipt-only delta over `dd7e4ac`; `src/`, `tests/`, `scripts/`, `docs/` unchanged)

---

## 1. Exact audited commits

| Role | SHA | Note |
|---|---|---|
| Original audit report | `806270b26435f2ff1513e939fcc2a8abdfb3e4b9` | Introduced `research/grok-milestone-1-audit.md` |
| Primary hardening | `6ee99e2bf89527dadf09d8c8b81c87af4dc69adc` | HMAC authority, recovery proofs, roots, IDs, tests |
| Exact tested source | `dd7e4acf36b6585735ec07045a9a25455eb51df2` | `fix: exclude generated public workspace files` |
| Receipt-only / current tip | `42b007e0c6b39ea372c49e9e7c95a0e6a2a8b107` | Only `evidence/milestone-1-substrate.json` |

`git diff --name-only dd7e4ac 42b007e` → `evidence/milestone-1-substrate.json` only.

---

## 2. Reproduction result

### Pytest

| Field | Value |
|---|---|
| Command | `.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q` |
| Result | `27 passed in 22.68s` (exit 0) |
| Collected / passed | 27 / 27 |
| Warnings | None from pytest |

### Live verifier (output redirected off-repo to avoid modifying the tree)

| Field | Value |
|---|---|
| Command | `.\.venv\Scripts\python.exe scripts\verify_milestone_1.py --output $env:TEMP\m1-reaudit-receipt.json` |
| Result | pytest nested run `27 passed in 22.85s`; wrote temp receipt; exit 0 |
| Regenerated? | Yes, from live fixtures and live checks |
| Match vs committed | Semantic content equal after excluding `timestamp`, absolute `verification.command` / `pytest_command` paths, and `tested_source_commit` |
| Roots / auth / public equality | Exact match to committed receipt |
| Committed `tested_source_commit` | `dd7e4acf36b6585735ec07045a9a25455eb51df2` — **correct** |
| Live regenerate at tip sets | `42b007e…` (because the script calls `git rev-parse HEAD`) |

The committed receipt correctly identifies the tested source as `dd7e4ac`. Regenerating at the receipt tip without an explicit source override would relabel the tip; that is a workflow caveat, not a falsification of the committed evidence.

---

## 3. Original finding closure table

| ID | Original finding | Status |
|---|---|---|
| **C1** | Forgeable snapshot digest / public “signature” | **FIXED** |
| **C2** | Direct mutation + forged `snapshot_restore` audit accepted | **FIXED** |
| **C3** | Circular receipt `leak_check.passed` assertion | **FIXED** |
| **M1** | Member-shaped IDs (`evt-041-a` / `evt-041-b`) | **FIXED** |
| **M2** | Hard-coded `attempt_budget` / revision diff | **FIXED** |
| **M3** | Missing deployment/runtime roots | **FIXED** |
| **M4** | Fixed-list-only leak testing | **FIXED** (complete public-surface enumeration is primary; secondary token list remains defense-in-depth) |
| **M5** | Restore allowed over invalid prior audit chain | **FIXED** |
| **M6** | Construction-order determinism absent from suite | **FIXED** |
| Telemetry `AUTOINCREMENT` | Determinism fragility | **FIXED** (explicit `MAX(seq)+1`; schema asserts no AUTOINCREMENT) |
| Artifact-derived revision diff | Hard-coded string | **FIXED** (`difflib` over `r0`/`r1` deployment artifacts) |

---

## 4. Snapshot authentication attack results

Authentication uses HMAC-SHA256 via `RecoveryAuthority`, with `hmac.compare_digest` for both snapshot and recovery tags (`authority.py`).

| Attack | Reached intended path? | Outcome |
|---|---|---|
| Alter payload | Yes | `snapshot_is_valid` false |
| Alter state root | Yes | rejected |
| Alter creation tick | Yes | rejected |
| Alter snapshot ID (reuse tag on new ID) | Yes | rejected |
| Alter auth tag | Yes | rejected |
| Copy A `S0` row into B | Yes | rejected (scopes/keys differ; semantic snapshot roots still match) |
| Insert new row with public digests, no authority | Yes | rejected |
| Wrong authority scope | Yes | rejected |
| Right key length, wrong key | Yes | rejected |
| Restore after unrelated service mutation | Yes | restore clears mutation; recovery valid |

**Secret leakage probe**

| Location | Authority key | Authority scope |
|---|---|---|
| SQLite bytes | Absent | Absent |
| Public workspace / status / logs / roots | Absent | Absent |
| Committed receipt | Absent | Absent |
| Filenames / paths | Absent | Absent |
| `auth_tag` column in SQLite | Present (tag, not key) — expected | — |

Committed privileged keys exist in `tests/milestone_1/conftest.py` and `scripts/verify_milestone_1.py`. That is acceptable for builder/test material and is explicitly out of any future agent mount. **Future agent-mount boundary remains NOT VERIFIED.**

---

## 5. Recovery-proof attack results

`recovery_is_valid()` independently requires: valid full audit chain; latest proof; current `state_root == post_state_root`; authenticated snapshot; HMAC-valid proof fields; matching audit transition row; `prior_audit_root == audit root through audit_seq-1`.

| Attack | Reached path? | Outcome |
|---|---|---|
| Direct mutation + generic `snapshot_restore` audit | Yes | rejected |
| Mutation + forged proof row (fake tag) | Yes | rejected |
| Copy valid A proof into B | Yes | rejected |
| Modify pre-state root on valid proof | Yes | rejected |
| Modify post-state root | Yes | rejected |
| Modify snapshot ID | Yes | rejected |
| Modify restore tick | Yes | rejected |
| Modify actor/scope | Yes | rejected |
| Modify linked audit seq / entry hash | Yes | rejected |
| Corrupt prior audit chain before restore | Yes | restore blocked; no proof written; service state unchanged |
| Corrupt audit chain after restore | Yes | `recovery_is_valid` false |
| Replay old valid proof after later state mutation | Yes | rejected |

No successful unauthorized recovery path was found under DB-only forgery without the privilege capability.

---

## 6. Identifier and leakage review

Seeded IDs use opaque `evt_|efx_|cmd_|occ_` + 32 hex form. Examples:

- Shared primary event: `evt_74c31f146a5d4e198f83b2d7619a0c5e`
- B additional event: `evt_c92580b73e124da59b641f037a6e82d4`

| Check | Result |
|---|---|
| No `-a`/`-b` / member-name suffixes | Pass |
| Same neutral format | Pass |
| A: one event identity, two effects, one source event | Pass |
| B: two event identities, one occurrence, two source events | Pass |
| First shared identity matched | Pass |
| Cardinality differs only for semantics | Pass (`journal` 1 vs 2) |
| Old IDs in `src` / public workspace / receipt | Absent as values |
| Old ID strings in repo | Only as **forbidden tokens** in leak scanners |

Public surfaces for A and B remain equal. Package builder still uses an internal `profile: int` parameter; it is not public and does not appear in status/logs/receipts.

---

## 7. Config/diff derivation review

| Check | Result |
|---|---|
| Public `attempt_budget` from active revision artifact | Pass (`tomllib` on deployment `config_bytes`) |
| Revision diff from r0/r1 artifacts | Pass (`difflib.unified_diff`) |
| Deployment `config_root` matches artifact bytes | Pass (checked in `_revision_artifact` / `_active_revision`) |
| Mutating r1 artifact changes budget/root | Pass (`attempt_budget` became 7; config root diverged) |
| No stale hard-coded public budget/diff authority | Pass |
| A/B public status and diff identical | Pass |

Workspace `settings.toml` still contains `attempt_budget = 1` as the active public file; that is the r1 artifact content, not a bypass of derivation.

---

## 8. Root-boundary review

Independent roots observed: `source`, `config`, `service_state`, `deployment`, `runtime`, `telemetry`, `audit`, `snapshot`.

| Mutation | Roots that changed |
|---|---|
| Deployment activation tick only | `deployment` only |
| Fake tick only | `runtime` only |
| Intake only | `runtime` only |
| Service data only | `service_state` only |
| Append telemetry only | `telemetry` only |
| Append audit only | `audit` only |
| Change `auth_tag` only | `snapshot` **stable**; authentication becomes invalid |

Auth tags are excluded from semantic snapshot roots by design. Authority secrets are not included in any root.

---

## 9. Determinism / workspace review

| Check | Result |
|---|---|
| A→B vs B→A construction | Covered by suite + consistent with prior auditor runs |
| Repeated clean process runs | Suite (`_process_probe.py`) |
| Paths with spaces / Unicode | Suite |
| Irrelevant env vars | Suite |
| Different CWDs | Suite |
| Deterministic telemetry seq | Explicit integers; no AUTOINCREMENT |
| Copied workspace file set | Exactly five intended files |
| No `__pycache__` / `.pyc` / `.pyo` | Pass (`ignore_patterns` + live listing) |

Binary-breakage of the leak scanner was not separately weaponized; public files are text and the enumerator hashes raw bytes, so binary content would not crash JSON encoding of digests. Residual residual risk for a future binary public asset is low and non-blocking.

---

## 10. Receipt-generation review

`scripts/verify_milestone_1.py`:

| Requirement | Result |
|---|---|
| Truly runs pytest | Yes (`subprocess` of `pytest tests/milestone_1 -q`) |
| Stops on pytest failure | Yes (`raise RuntimeError`) |
| Creates fresh fixtures | Yes |
| Recomputes roots and public equality | Yes |
| Executes snapshot/recovery attacks | Yes (`_snapshot_checks`) |
| Leak enumeration | Yes (full channel map + secondary tokens + package metadata scan) |
| Writes receipt only from live results | Yes |
| No trust of old receipt booleans | Yes |
| Test count from pytest stdout | Yes (`(\d+) passed`) |
| No key / tag / selector / raw privileged state / causal answer in receipt | Yes (live + committed checked) |

**Minor:** verification commands embed absolute Windows interpreter paths, reducing cross-machine string portability without affecting semantic evidence.

**Minor workflow:** `_git_head()` labels whatever tip is checked out. The receipt-only tip correctly preserved `tested_source_commit = dd7e4ac` in the committed file; operators regenerating at tip must preserve that binding intentionally.

---

## 11. Remaining findings

### Critical

None.

### Major

None.

### Minor

1. Absolute Windows paths in receipt `verification.command` / `pytest_command`.
2. Live `verify_milestone_1.py` at a receipt-only tip would rewrite `tested_source_commit` to that tip unless generation is done on the source commit or an override is added later.
3. Secondary leak scanners still use a fixed forbidden-token list (now including old IDs); primary protection is full public-surface equality enumeration.

---

## 12. Claims still NOT VERIFIED

- Future **agent-mount** isolation (privileged package source, fixture DBs, tests, scripts, keys, receipts must not be mounted). Correctly labelled **NOT VERIFIED** in README, boundary doc, and receipt limitations.
- Production OS / process / container sandboxing.
- Milestone 2 tool API, hidden workloads, oracle grading, model evaluation.
- That an agent with filesystem access to the whole repository could not import test/script keys (depends on packaging not yet built).

---

## 13. Final verdict

### PASS — Milestone 1 may close

All original critical and major findings were independently re-attacked and did not reproduce. Hardening matches the documented local-HMAC boundary without overclaiming production isolation.

---

## Closure statement

| Question | Answer |
|---|---|
| May Milestone 1 close? | **Yes** |
| May Milestone 2 begin? | **Yes, only after explicit user approval** (per `AGENTS.md`); technical gate from this re-audit is clear |
| Critical / major / minor | **0 / 0 / 3** |
| Strongest remaining risk | Accidental future mounting of privileged builder/test/key material into an agent runtime |
| Future agent-mount boundary labelled NOT VERIFIED? | **Yes** — correctly and consistently |
