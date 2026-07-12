# Milestone 2 targeted closure re-audit

**Role:** falsify-by-default re-check of remediation for original findings C1 and M1–M5  
**Scope:** read-only; create only this report  
**Deferred:** Milestone 3, hidden verifier, gold solutions, cheat battery, model evaluation  

**Original audit:** `research/grok-milestone-2-audit.md` (verdict PASS WITH FIXES)

---

## 1. Exact audited commits

| Role | Full SHA | Note |
|---|---|---|
| Remediation source | `ba8d5e1b166034aae59f4309a569f403328785e6` | `Implement Milestone 2 audit remediation.` |
| Receipt tip | `1d6b01c08d3f365fbc0acc20b2a22c342f13acf1` | `Regenerate evidence receipts for Milestone 1 and Milestone 2.` |

Both SHAs are on `origin/main`.

### Receipt-only commit structure

`git show --stat 1d6b01c` changes **only**:

- `evidence/milestone-1-substrate.json`
- `evidence/milestone-2-interaction-layer.json`

No source, tests, scripts, or docs in that commit.

Both receipts set:

```text
tested_source_commit = ba8d5e1b166034aae59f4309a569f403328785e6
git_sha_status = tested-source-commit
```

They do **not** claim that `1d6b01c` tested itself.

### Why the M1 receipt was regenerated

Source commit `ba8d5e1` also touched Milestone 1 test imports (`from …conftest` → package-safe imports), empty `__init__.py` packages, and `scripts/verify_milestone_1.py` (`--source-commit`). The receipt tip re-ran M1 verification against that tree and rebound the M1 receipt.

Observed M1 receipt delta vs prior tip: essentially **`tested_source_commit` + `timestamp`** (semantic roots and check booleans unchanged). The regenerated M1 receipt:

- milestone `milestone-1-substrate-hardened` only;
- no Milestone 2-only claims;
- preserves NOT VERIFIED limitations (OS/container isolation; future agent-mount; tools/hidden grading outside M1);
- matches a fresh `verify_milestone_1.py --source-commit ba8d5e1…` run after scrubbing timestamp and machine paths (**True**).

---

## 2. Reproduction results

### Commands

```powershell
.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q
.\.venv\Scripts\python.exe -m pytest tests\milestone_2 -q
.\.venv\Scripts\python.exe -m pytest tests -q

.\.venv\Scripts\python.exe scripts\verify_milestone_1.py `
  --source-commit ba8d5e1b166034aae59f4309a569f403328785e6 `
  --output $env:TEMP\m1-targeted.json

.\.venv\Scripts\python.exe scripts\verify_milestone_2.py `
  --source-commit ba8d5e1b166034aae59f4309a569f403328785e6 `
  --output $env:TEMP\m2-targeted.json
```

### Counts and outcomes

| Run | Result |
|---|---|
| M1 pytest | **27 passed** (~18s); exit 0; no warnings observed |
| M2 pytest | **16 passed** (~18s); exit 0 |
| Combined `pytest tests` | **43 passed** (~39s); exit 0 |
| `verify_milestone_1.py` → temp | Nested 27 passed; wrote temp; exit 0; preserves `--source-commit` |
| `verify_milestone_2.py` → temp | Nested **43 passed** (`pytest tests`); live gateway evidence; exit 0; preserves `--source-commit` |

### Receipt match

| Receipt | Semantic match after excluding timestamp + machine command paths |
|---|---|
| M1 | **Equal** (including when commit field retained under explicit bind) |
| M2 | **Not byte-equal**: per-run `handle_salt` changes handles and therefore **telemetry roots**; `required_checks` and behavioral public/diagnostic structure match. Equality holds for check booleans and non-handle public fields when handles/telemetry roots are treated as session-ephemeral |

### Composite verification behavior

`verify_milestone_2.py` runs **`pytest tests`** (M1+M2 together) then live gateway checks. It reports a **single** live `verification.test_count` (43). It does **not** emit separate `milestone_1_test_count` / `milestone_2_test_count` / `total_test_count` fields. Failure of the combined pytest fails the entrypoint closed.

---

## 3. Receipt-diff and source-binding review

### Source-binding attacks

| Attack | Result |
|---|---|
| `--source-commit` nonexistent / garbage SHA | **Accepted** — receipt written with that string; exit 0 |
| Explicit valid source SHA at receipt tip | **Preserved** (not replaced by HEAD) |
| Dirty-tree / receipt-only-diff gate | **Not implemented** in either verifier |
| Default without override | Uses `git rev-parse HEAD` |

**Assessment:** `--source-commit` preserves an explicit bind when operators use it correctly. It does **not** validate that the SHA exists, that the tree matches that commit, or that only receipt files differ. Source-binding remains an **operator workflow**, not an enforced gate.

### README / AGENTS stage

Both still describe **“Milestone 2 audit remediation”** / fixes in progress, not closure. Accurate for a pre-acceptance tip; they should be updated when Milestone 2 is formally closed.

---

## 4. Gateway attack matrix (C1)

Intended evaluated surface: `ToolGateway` → subprocess controller → JSON-lines → `ToolClient` (pipes only; no `AgentSession`).

### Client surface

| Check | Result |
|---|---|
| `_store` / `_profile` / `_fixture` on `ToolClient` | **Absent** |
| Tool inventory | Exact twelve tools |
| Session tree | Only `active|candidate|initial/service/*` + `metadata.json` |

### Raw JSON-lines attacks

| Attack | Gateway response |
|---|---|
| Tool `_store`, `__class__`, `connection`, empty name | `unknown tool …` |
| Missing `tool` | `tool execution failed` |
| Extra top-level fields | Ignored; `release.status` succeeds |
| Wrong argument types | `tool execution failed` |
| `arguments` as list | `arguments must be an object` |
| Trailing non-JSON / invalid JSON | `invalid JSON` |
| Two JSON objects (two lines) | First handled; second readable as next response |
| Oversized edit content | Rejected / fails closed without privileged leak in exercised path |
| Child process kill | Client: `gateway closed connection` |
| Response leak scan (traceback, sqlite, profile, drive path, key hex) | **None observed** in error envelopes |

### Dispatch implementation

- Fixed `_TOOL_MAP` with exactly the twelve tools (+ `system.close`, `system.leak_probe`).
- Controller still uses `getattr(self._session, method_name)` **only after** map lookup (not arbitrary user-controlled getattr).
- No `eval`, no import-by-name from requests, no dynamic tool registration from input.
- Privileged Python objects do not cross the JSON boundary.
- Controller process **does** put repository `src` on `PYTHONPATH` (privileged side). A future evaluated agent process with stripped import path remains **packaging-dependent**.

**Boundary class:** local **process/tool** separation. **OS/container isolation: NOT VERIFIED.**

---

## 5. Error-normalization matrix (M1)

Agent-visible failures through the gateway are JSON `{"id", "error": {"message": …}}`. `ToolClient` re-raises `ToolError(message)`.

| Path | Message (bounded) | Raw exception type crossing gateway? |
|---|---|---|
| Double pause | `intake is not open` | No (wrapped) |
| Restore while open | `intake must be paused` | No |
| Invalid rollback | `rollback supports r0 or r1` | No |
| No-op deploy (candidate≡active) | `no candidate changes to deploy` | No |
| Repeated no-op deploy | same | No |
| Abs / `..` path | `path outside workspace` | No |
| NUL path | `invalid path` | No |
| Fabricated handle | `invalid trace handle` / `invalid trace source` | No |
| Empty/invalid selector | `invalid progress selector` / `selector is empty` | No |
| Resume without checks | `intake must be paused` / other gate messages | No |
| Invalid settings.toml after deploy | `active workspace configuration invalid` | No |

No `RuntimeError` / `ValueError` / `KeyError` / SQLite / traceback **type names** observed in envelopes. There are **no documented numeric/string error codes** in the codebase—only free-form neutral messages. Substrate wording such as `intake is not open` still appears as the message text.

---

## 6. Composite-verifier review (M2)

| Requirement | Observed |
|---|---|
| Runs Milestone 1 tests | **Yes** (via `pytest tests`) |
| Runs Milestone 2 tests | **Yes** |
| Gateway-level live checks | **Yes** (`ToolGateway` paired flow) |
| Separate `milestone_1_test_count` | **No** |
| Separate `milestone_2_test_count` | **No** |
| Separate `total_test_count` | **No** (single `test_count: 43`) |
| Fail closed if either suite fails | **Yes** (combined pytest nonzero → abort) |
| Does not load success from committed receipt | **Yes** |

---

## 7. Leak-probe attack matrix (M3)

`system.leak_probe` is invoked **through the gateway** and runs inside the controller. It performs:

- forbidden name presence under `session_dir`;
- token greps including fixture DB path string;
- env / argv token checks;
- `python -S` import isolation probe with `PYTHONPATH` stripped.

| Attack / access | Through evaluated tools / probe? | Result |
|---|---|---|
| Fixture DB via `workspace.read` | Attempted | Outside workspace / not in session tree |
| Profile / member via tools | Attempted | Not in responses; client has no `_profile` |
| Authority keys/scopes via tools | Attempted | Not in envelopes / session files |
| `handle_salt` in session files / SQLite bytes | Inspected | **Absent** |
| Repo `src`, tests, evidence, research, `.git` in session | Enumerated | **Absent** |
| Env / argv privileged tokens | Probe | Pass when unset |
| Traversal / abs / mixed / NUL / oversized | Tools | Denied with neutral errors |
| Symlink/junction escape | | **NOT VERIFIED** (not exercised beyond resolve checks) |

**Assessment:** deeper than the original filename-only probe, and reachable via the gateway. Still primarily a **controller-side hygiene scan**, not a full adversarial mount battery. Supporting, not sufficient alone for OS isolation claims.

---

## 8. Capability-token attack matrix (M4)

### Mechanism

Handles are **`h_` + truncated digest** over canonical JSON that includes a per-session `secrets.token_hex(32)` **`handle_salt`**. They are **salted content hashes**, not HMAC capability tokens. Validation is **store existence** of `trace_spans` for that handle. No selector/view capability encoding; no epoch.

Salt does **not** appear in SQLite bytes, session files, gateway responses, or receipts in probes.

### Attacks

| Attack | Result |
|---|---|
| Derive from known workload/cutpoint/tick/run **without salt** | Rejected |
| Mutate one character | Rejected |
| Fabricate / wrong salt | Rejected |
| Cross-session / A→B | Rejected |
| Broaden empty selector | Rejected (`selector is empty`) |
| Reuse after rollback | **Still valid** |
| Reuse after restore | **Still valid** |
| Reuse after deploy | **Still valid** |
| Reuse after resume | Expected still valid (append-only traces; not separately invalidated) |

**Closure vs original bar:** guessing/tampering/cross-session fail → improved. Stale tokens after rollback/restore/deploy/resume are **not** rejected → **PARTIALLY FIXED** per the stated FIXED-only-if criterion.

---

## 9. Diagnostic-honesty results (M5)

| Member | Cutpoint | `outcome` | Counts |
|---|---|---|---|
| A | `s5.exit` | **`cutpoint`** | effects 2, events 1 |
| A | `s2.exit` | **`diagnostic`** | 1 / 1 |
| B | `s5.exit` | **`diagnostic`** | 1 / 1 |
| B | `s2.exit` | **`cutpoint`** | effects 2, events 2 |

`cutpoint` appears only when the interrupt actually triggered. Wrong experiments remain runnable and non-diagnostic. No member/profile label or causal prose in tool payloads.

---

## 10. Deployment / public-credit results

| Check | Result |
|---|---|
| Public pass set keyed by **active config root** | **Yes** |
| Restore clears credit for current config root | **Yes** (`pop` on restore) |
| Stale credit after deploy of different config | Resume → `public workloads not passed` |
| No-op deploy when candidate≡active | `no candidate changes to deploy` |
| Repeated deploy without new edit | Same rejection |
| After `rollback r0`, candidate still differs from active | Deploy **without** further edit **succeeds** (real root change: reactivates prior candidate bytes)—not a no-op |
| Deploy activates candidate bytes / computed roots | **Yes**; no agent-supplied root argument |
| Settings edit behaviorally load-bearing | **Yes** (`RuntimeEngine` reads `settings.toml`) |
| Historical P1–P3 on `r0` then unsafe candidate deploy then resume | **Blocked** (original C2 class defect remediated) |

---

## 11. Closure table

| ID | Original finding | Status |
|---|---|---|
| **C1** | No hardened dispatcher; live `AgentSession` exposes `_store` / `_profile` | **FIXED** (process-separated JSON gateway + `ToolClient`; residual: controller-side `getattr` after fixed map; OS/container mount **NOT VERIFIED**) |
| **M1** | Raw `RuntimeError` / non-neutral exceptions | **FIXED** (JSON error envelopes; no exception types/tracebacks). **Caveat:** free-form messages, not documented error codes |
| **M2** | M1 regression missing from M2 verifier | **PARTIALLY FIXED** (runs `pytest tests` including M1; no separate live count fields) |
| **M3** | Shallow leak probe | **PARTIALLY FIXED** (gateway-invoked deeper probe + import/env checks; not a full mount attack oracle) |
| **M4** | Predictable / replayable handles | **PARTIALLY FIXED** (per-session salt blocks guessing/cross-session; **no** capability epoch / invalidation after rollback/restore/deploy/resume) |
| **M5** | Dishonest diagnostic `outcome` | **FIXED** |

### Related remediation reviewed

| Item | Status |
|---|---|
| No-op deployment | **FIXED** when roots equal; divergent candidate after rollback is a real deploy |
| Public-credit / unsafe resume (orig. C2 class) | **FIXED** |
| Source-binding workflow enforcement | **NOT FIXED** (override string trusted; no dirty-tree/SHA existence gate) |
| M1 receipt regeneration | **Honest** bind to `ba8d5e1…`; M1-only claims |
| README / AGENTS stage text | Still “remediation in progress” — update on formal close |

---

## 12. Remaining critical / major / minor issues

### Critical

None re-opened against the intended gateway-evaluated surface.

### Major

| ID | Issue |
|---|---|
| **R1** | Source-binding verifiers accept arbitrary `--source-commit` strings and do not enforce clean/dirty policy. |
| **R2** | M4 handles remain valid across rollback/restore/deploy/resume (store-local salted IDs, not epoch-bound capabilities). |

### Minor

| ID | Issue |
|---|---|
| **r1** | M2 receipt lacks separate M1/M2/total count fields. |
| **r2** | No documented error-code enum (messages only). |
| **r3** | Controller `_dispatch` uses `getattr` after a fixed map. |
| **r4** | Per-run `handle_salt` makes handle strings and telemetry roots non-reproducible across receipt regenerations. |
| **r5** | README/AGENTS still say audit remediation, not closed. |

---

## 13. Claims still NOT VERIFIED

- OS, container, network, or production process isolation of an evaluated agent image.
- Packaging that omits `src`, tests, evidence, research, keys, and fixture DBs from the agent mount / import path.
- Symlink/junction workspace escapes on all platforms.
- Hidden verifier, gold solutions, cheat controls, model evaluation, ≥15-action horizon measurement.
- That operators will always pass the correct `--source-commit` when writing tip receipts.

---

## 14. Final verdict

### **PASS WITH MINOR FIXES**

Critical gateway boundary (**C1**), exception channel (**M1**), diagnostic honesty (**M5**), and the load-bearing public-credit / no-op-deploy defects are remediated under live attack. Milestone 1 remains green; the composite M2 entrypoint reruns the full 43-test baseline through the gateway and binds receipts to `ba8d5e1…` when instructed.

Remaining gaps (**R1** source-binding enforcement, **R2** handle epoch, separate test-count fields, receipt telemetry nondeterminism from salts) are real but do not re-break the interaction-layer design the original audit required for closure of C1/C2-class failures.

### May Milestone 2 close?

**Yes**, if the user accepts the residuals above as documented limitations (especially: handles are salted session-local correlation IDs without invalidation epochs; source-commit binding is operator-enforced; OS/container mount remains NOT VERIFIED).

### May Milestone 3 work begin?

**Yes, after the user explicitly accepts this re-audit and closes Milestone 2.** Do not start hidden verification, gold solutions, cheat controls, or model evaluation until that approval.

---

*Auditor note: probes used temporary fixtures and temp receipt outputs; implementation, tests, committed receipts, `AGENTS.md`, and docs were not modified. Working tree was audited at receipt tip `1d6b01c` with source bind `ba8d5e1`.*
