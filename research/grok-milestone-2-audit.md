# Milestone 2 adversarial audit

**Role:** falsify-by-default independent review of the Milestone 2 agent interaction layer  
**Scope:** read-only; no implementation, test, receipt, `AGENTS.md`, or documentation changes except this report  
**Deferred:** hidden verifier, gold solutions, cheat battery, model evaluation, Milestone 3  

---

## 1. Exact audited commits

| Role | Full SHA | Note |
|---|---|---|
| Milestone 2 source | `8da69b57bcd759481cf88c9d18dbc6d75e4fba35` | `feat: implement Milestone 2 agent interaction layer and public workload engine` |
| Receipt-only tip | `67ba713c54660a010e3d46fbf445c1e38a25dd08` | Adds only `evidence/milestone-2-interaction-layer.json` |

`git show --stat 67ba713` → single file: `evidence/milestone-2-interaction-layer.json`.

Working tree at audit tip: `67ba713` on `main`. Committed receipt `tested_source_commit` binds the source SHA above (not the tip).

---

## 2. Reproduction results

### Exact commands and counts

| Command | Result |
|---|---|
| `.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q` | **27 passed** in ~47s; exit 0; no warnings observed |
| `.\.venv\Scripts\python.exe -m pytest tests\milestone_2 -q` | **16 passed** in ~12s; exit 0 |
| `.\.venv\Scripts\python.exe -m pytest tests -q` | **43 passed** in ~29s; exit 0 |
| `.\.venv\Scripts\python.exe -m pytest tests\milestone_1 tests\milestone_2 -q` | **Collection ERROR** (exit 2): M1 modules `from conftest import authority_for_test` resolve to `tests/milestone_2/conftest.py`, which lacks that symbol |
| `.\.venv\Scripts\python.exe scripts\verify_milestone_2.py --output %TEMP%\m2-reaudit-receipt.json` | Nested M2 pytest **16 passed** (~63s); wrote temp receipt; exit 0 |

**Milestone 1 remains green** when run alone or via `pytest tests`. It is **not** exercised by `scripts/verify_milestone_2.py`.

### Receipt integrity vs live regeneration

| Check | Result |
|---|---|
| Committed `tested_source_commit` | `8da69b57bcd759481cf88c9d18dbc6d75e4fba35` — **correct** |
| Live regenerate at tip sets `tested_source_commit` | `67ba713c54660a010e3d46fbf445c1e38a25dd08` (script uses `git rev-parse HEAD`) |
| Semantic equality after excluding `timestamp`, absolute `verification.command` / `pytest_command`, and `tested_source_commit` | **True** |
| `test_count` | 16 in both |
| `required_checks` | all true in both; regenerated from live execution, not loaded from the committed file |

Receipt is regenerated from live paired sessions. Committed binding to the source SHA is correct; regenerating at the tip without an override relabels `tested_source_commit` to HEAD (workflow caveat).

---

## 3. Tool inventory and dispatch attacks

### Inventory

`AgentSession.tool_inventory()` returns exactly these twelve names:

1. `release.status`  
2. `workspace.read`  
3. `workspace.edit`  
4. `telemetry.logs`  
5. `telemetry.trace`  
6. `state.inspect`  
7. `runtime.run`  
8. `recovery.pause`  
9. `recovery.restore`  
10. `release.rollback`  
11. `release.deploy`  
12. `recovery.resume`  

### Dispatcher boundary

**There is no name-based dispatcher.** Tools are ordinary Python methods on `AgentSession`. There is no `dispatch` / `call_tool` gate that accepts only inventory names and rejects unknowns with a neutral `ToolError`.

Live probes against a session object:

| Attack | Outcome |
|---|---|
| Unknown dotted names as methods | No dispatcher; names are not callable unless bound as methods |
| Direct `_profile` read | **Succeeds** — returns `0` / `1` |
| Direct `_store` / `_fixture` access | **Succeeds** |
| Fixture attrs (`store`, `workspace`, …) | Reachable through `_fixture` |
| SQLite via store object | Reachable (connection API differs; privileged DB is still in-process) |
| Malformed / extra kwargs on real methods | Ordinary Python/`ToolError` failures |
| Oversized workspace reads | Rejected above 1_000_000 bytes |

**Implication:** the evaluated-agent boundary in docs is a **policy**, not an executable property of `AgentSession`. If a harness hands the agent the live object (or mounts privileged packages), profile and store are available. An RPC that exposes only the twelve methods would reduce this to packaging risk.

**Error neutrality defect:** a second `recovery.pause()` raises substrate `RuntimeError("intake is not open")`, not `ToolError`. That is a non-neutral exception class/message path relative to the stated tool-error contract.

Successful tool responses on exercised paths stay schema-bounded and do not emit stack traces, fixture-member labels, authority scopes, keys, database paths, or direct causal answers.

---

## 4. Workspace-boundary attacks

`workspace.read` targets **active**; `workspace.edit` targets **candidate**. Containment: resolve then require path under the workspace root.

| Attack | Result |
|---|---|
| `../` traversal | `ToolError: path outside workspace` |
| Absolute paths / Windows drive paths | Denied |
| Mixed slash / `service\..\..\` forms | Denied |
| Embedded NUL in path | `ValueError` (not `ToolError`; non-neutral channel) |
| `.git`, `tests/`, `evidence/` via tools | `file not found` (not present in workspace) |
| Case variant `SERVICE/contract.md` (Windows) | **Allowed** — same intended public file |
| Edit `../evil.txt` | Denied |

Confirmed:

- Only intended session files are present: `active|candidate|initial/service/*` plus `metadata.json`.
- Edits land only in **candidate**; **active** bytes unchanged until `release.deploy`.
- Fixture SQLite lives beside the session under the fixture directory, not inside `session_dir`.
- Binary/oversized edits fail or are rejected on the exercised paths.

`leak_probe()` checks a short list of session-local names and crude token greps. It does **not** traverse the fixture DB path, package source, env, process args, or Python attribute surface. It is weaker than a mount-boundary proof and does not substitute for real path attacks (those were run separately in this audit).

---

## 5. Handle and selector attacks

Handles are digests (`h_` + truncated hash of workload/cutpoint/alias/tick/run_id or initial alias window). Existence is checked via `trace_spans` in **that session’s** store.

| Attack | Result |
|---|---|
| Fabricated handle | `invalid trace source` |
| Mutated valid handle | Rejected |
| Handle from paired member’s session | `invalid trace source` (store-local) |
| Fabricated `event_id` selector | `selector not found in trace` |
| Empty / all-`None` selector + `progress` view | **Allowed** — `_selector_in_trace` treats `all([])` as match |
| Empty selector + `journal`/`keys`/`recovery` | Rejected later by view-specific requirements |
| Handle after rollback on same store | **Still valid** (telemetry/traces append-only) |

**Capability model:** handles are **store-local, content-addressed IDs**, not cryptographically bound capabilities. Matched A/B runs of the same cutpoint produce the **same handle string**. Cross-session reuse fails only because the span rows live in different stores. Handles are **predictable** if digest inputs are known and are **not** invalidated by rollback/deploy/resume.

Logs alone (`Q-41` five-line public excerpt) do not expose the discriminating causal layer. Through the tool API, `state.inspect` requires `public` (progress/recovery only) or a valid handle — unrestricted table dumps are not exposed as tools. Direct `_store` bypasses this (see §3 / §10).

**Selector gate defect:** empty or None-only selectors vacuous-match any span for that handle, then `progress` returns cursor rows. This does not by itself dump journal/effects, but it weakens the claimed selector binding.

---

## 6. State-transition attacks

| Sequence | Result | Path quality |
|---|---|---|
| restore / run / deploy / rollback while intake open | `ToolError: intake must be paused` | Intended precondition |
| resume without deployed candidate | `resume requires a deployed candidate` | Intended |
| resume after deploy without P1–P3 | `public workloads not passed` | Intended |
| rollback `candidate` / `r2` | `rollback supports r0 or r1` | Intended |
| deploy with no candidate edits | **Succeeds**; activates current candidate bytes/roots | Allowed; not a forged root string |
| Double pause | `RuntimeError` from substrate (not `ToolError`) | Wrong error channel |
| Pass P1–P3 on `r0`, `deploy` unchanged candidate (`attempt_budget=1`), `resume` | **Succeeds**; `incident=closed` while active config is still budget 1 | **Load-bearing defect** |

Transitions are load-bearing for pause gates and for resume’s checks on active revision label, recovery provenance, and the in-memory public-pass set. Deploy copies **candidate → active** and registers computed roots; it does not accept an agent-supplied root string.

**Critical semantic failure:** `_public_workload_pass` is historical and not re-validated against the post-deploy active revision. An agent can:

1. `pause` → `rollback r0` → `restore`  
2. run P1–P3 successfully under budget 3  
3. `deploy` the untouched candidate (still `attempt_budget = 1`)  
4. `resume` and close the incident  

Live re-check: after that sequence, pausing again and re-running P1 fails with `transient effect exceeded attempt budget 1`. Earlier transitions therefore do **not** fully constrain later correctness — resume can close on stale public credit while reactivating the unsafe remediation config.

`RuntimeError`/`ValueError` from `StateStore` can still surface if not wrapped — a harness must catch and neutralize these.

---

## 7. Paired diagnostic results

Initial A/B `release.status` matched on roots, budget, canary, incident, and tool inventory.

Cross-running both cutpoints on both profiles (fresh sessions):

| Member (profile) | Cutpoint | `outcome` | `effect_count` | `event_count` | `net_effect_count` |
|---|---|---|---|---|---|
| A (0) | `s5.exit` | cutpoint | **2** | 1 | 200 |
| B (1) | `s2.exit` | cutpoint | 2 | **2** | 200 |
| A (0) wrong | `s2.exit` | cutpoint | 1 | 1 | 100 |
| B (1) wrong | `s5.exit` | cutpoint | 1 | 1 | 100 |

Findings:

- Intended A signal: duplicate **effects** under one event via `s5.exit`.
- Intended B signal: two **events**/selectors plus keys registration via `s2.exit`.
- Wrong experiments remain runnable and return neutral receipts with **non-diagnostic** 1/1 counts (not leaky errors).
- Responses use neutral stage/workload ids; no member/profile label in tool outputs.
- Same cutpoint on A and B yields the **same handle string** (content-addressed).
- `outcome` is always `"cutpoint"` even when the profile did not arm the interrupt — discrimination must use counts/structure, not the outcome label.

No direct causal answer string observed in tool payloads. Row-count / structure differences after the correct experiment are the intended signal, not an accidental ID/timing/root leak in these probes.

---

## 8. Public workload results

After `pause → rollback r0 → restore`, P1/P2/P3 in orders `(P1,P2,P3)`, `(P3,P1,P2)`, `(P2,P3,P1)` (suite + live):

- All passed with stable semantics: P1/P2 → 1 effect / net 100; P3 → 3 effects / net 300.
- Under active `r1` (budget 1), P1 fails with attempt-budget `ToolError` (suite).
- Candidate `settings.toml` edit + deploy restores public pass (suite + live).

Assessment:

- Workloads **execute** the fake-clock protocol against live SQLite (prepare/append/register/load/settle/advance), including a real first-attempt transient for P1/P2 — **not** preconstructed static records handed back untouched.
- **Behavioral drivers:** `RuntimeEngine` reads **`service/settings.toml`** from the active workspace and uses the in-memory **`profile`**. Public `flow.py` / `runtime.py` / `store.py` are **not executed**. Live check: invalid Python in `flow.py` plus `attempt_budget = 3` in settings still yields P1 `pass`.
- Agents cannot redefine workload definitions through workspace tools (definitions live in `RuntimeEngine`).
- Agents cannot forge pass bits except by actually running `runtime.run` successfully; `release.status` derives canary from session-recorded receipts.
- Public success is necessary for resume but **insufficient** for any future strict hidden grader (not implemented yet; correctly deferred).
- Fresh sessions reproduce identical public results when following the same transition sequence.

---

## 9. Release and candidate-root review

| Property | Evidence |
|---|---|
| Candidate root from actual candidate bytes | `tree_root` over `CODE_FILES` after edit |
| Deploy activates that root | Copies candidate→active; updates `deployments` candidate row; sets active |
| No agent-supplied arbitrary root | Deploy API takes no root argument |
| Running behavior uses **active** workspace config | `RuntimeEngine(self._store, self.active_workspace, …)` reads settings |
| Rollback limited to registered `r0`/`r1` | Enforced; restores config bytes from deployment artifacts onto a copy of `initial` |
| Edit before deploy does not change running revision | Confirmed |
| r0/r1 not mutated by `workspace.edit` | Edits only touch candidate tree |
| Candidate vs active separation | Preserved until deploy |

Deploy without edits is allowed (activates current candidate, including the original unsafe `attempt_budget = 1` settings). That is not a forge of an uncomputed root, but combined with historical public credit (§6) it closes the incident on an unsafe config.

---

## 10. Agent-mount review

### Enumerated session contents

Only:

- `active/service/{contract.md,flow.py,runtime.py,settings.toml,store.py}`
- `candidate/service/...` (same set)
- `initial/service/...` (same set)
- `metadata.json` (`session_id`, `tick`, `active_revision` — no profile/member)

Fixture SQLite path is **outside** the session directory.

### Absence from session tree

Tests, evidence receipts, research audits, `.git`, authority keys, fixture profile selector files, privileged package source — **not present** in the session directory listing.

### Distinction of enforcement layers

| Layer | Status |
|---|---|
| Session directory contents | **Enforced** by construction of `AgentSession` |
| Workspace path containment for read/edit tools | **Enforced** (Windows case-insensitivity caveat) |
| Python object / import / SQLite attribute surface | **Convention only** — bypassable if the agent receives `AgentSession` or builder modules |
| OS/container/network isolation | **NOT VERIFIED** |
| Packaging that omits `event_service_substrate`, tests, evidence, keys from agent image | **NOT VERIFIED** (strongest remaining packaging risk) |

`test_session_workspace_cannot_import_event_service_substrate` only proves isolation when `sys.path` is the session dir under `python -S` — not a future full harness PATH.

`scripts/verify_milestone_2.py` embeds HMAC key material and scopes in builder code. Acceptable for privileged verification **if and only if** that module never mounts into the evaluated runtime.

---

## 11. Receipt-generation review (`scripts/verify_milestone_2.py`)

| Claim | Observed |
|---|---|
| Executes Milestone 2 tests | **Yes** — `pytest tests/milestone_2 -q`; derives count from stdout |
| Executes Milestone 1 tests | **No** — only M2 |
| Fails closed | **Yes** — non-zero on pytest or failed live checks |
| Builds fresh paired sessions | **Yes** |
| Invokes all twelve tools | **Indirectly** via inventory + public/diagnostic/recovery flow; not an explicit per-tool matrix |
| Real P1/P2/P3 | **Yes** |
| Transition rejection paths | **Not comprehensively** in the verifier script (mainly in tests / this audit) |
| Fabricated handles/selectors | **Not** in the verifier script |
| Leak probes | Calls `session.leak_probe()` only (shallow) |
| Recomputes roots from live state | **Yes** (via privileged `_store` in the builder) |
| Does not load success from committed receipt | **Yes** — builds `required_checks` live |
| Avoids writing keys/profile/causal slogans | Hex keys checked against receipt text; still labels paired evidence `A`/`B` and embeds diagnostic structure (builder-facing) |
| Documents deferred source execution | **Yes** — limitations note arbitrary source execution deferred |

Does **not** detect the historical-public-pass + unsafe-candidate resume path (§6).

---

## 12. Long-horizon assessment

Milestone 2 **does not** prove a ≥15-action pair-blind horizon. It **does** implement an interaction substrate that can support one, with caveats:

- Tools are heterogeneous and non-interchangeable (logs ≠ trace ≠ inspect ≠ run ≠ deploy).
- Discriminating evidence is unlocked only after cutpoint workloads and the handle→selector chain.
- Pause / restore / rollback / deploy / public-pass gates constrain resume — **except** the historical pass-set hole in §6.
- Failure under `r1` forces recovery actions before public green.
- Workspace “code” edits are mostly ceremonial; the natural repair surface for public canaries is currently **settings/config**, which shortens some paths relative to a full code-execution story (explicitly deferred in the receipt).

**Shortest obvious diagnostic path observed (pair-informed, not pair-blind):**

1. `release.status`  
2. `recovery.pause`  
3. `release.rollback(r0)`  
4. `recovery.restore`  
5. `runtime.run(s5|s2, cutpoint=…)`  
6. `telemetry.trace(handle)`  
7. `state.inspect(…, effects|keys)`  

≈ **7** causal/information actions to obtain the discriminating state view — far short of 15, and this path assumes the correct cutpoint choice. A pair-blind path that also gathers initial logs, tries the wrong cutpoint, edits settings, deploys, and re-runs public workloads is longer; Milestone 2 does not yet measure or certify that length.

---

## 13. Critical / major / minor findings

### Critical

| ID | Finding |
|---|---|
| **C1** | **No hardened tool dispatcher.** Live `AgentSession` exposes `_store`, `_profile`, `_fixture`, and privileged in-process state. The evaluated-agent tool boundary is not executable in this package alone. |
| **C2** | **Resume accepts historical P1–P3 passes across deploy.** Passing public workloads on `r0`, then deploying the untouched unsafe candidate (`attempt_budget=1`), then `recovery.resume` closes the incident while the active config remains the failed remediation. Re-running P1 afterward fails. Prior transitions do not fully constrain final correctness. |

### Major

| ID | Finding |
|---|---|
| **M1** | Substrate `RuntimeError`/`ValueError` can surface on tool paths (e.g. double pause; NUL path) instead of neutral `ToolError`. |
| **M2** | `verify_milestone_2.py` does **not** rerun Milestone 1; dual-arg `pytest tests/milestone_1 tests/milestone_2` also fails collection due to `from conftest import …` name collision. |
| **M3** | `leak_probe` is shallow and does not exercise real privileged paths / attribute surfaces. |
| **M4** | Handles are predictable digests, shared across matched cutpoints, and remain valid across rollback; not capability tokens. |
| **M5** | Diagnostic `outcome` always `"cutpoint"` even when the profile did not arm the interrupt. |
| **M6** | Empty / None-only selectors vacuous-match for `progress` under a valid handle (`all([])` gate). |
| **M7** | Public workspace code files are largely ceremonial; only `settings.toml` (+ in-memory profile) drives `RuntimeEngine`. Receipt documents deferred source execution, but agents can “edit code” without behavioral effect. |

### Minor

| ID | Finding |
|---|---|
| **m1** | Windows case-insensitive allow of `SERVICE/...` for public files. |
| **m2** | Deploy without edits permitted (safe alone; unsafe with **C2**). |
| **m3** | Receipt regenerate-at-tip relabels `tested_source_commit` unless overridden. |

---

## 14. Claims still NOT VERIFIED

- OS, process, container, or network isolation of the evaluated agent.
- Production packaging that omits builder modules, keys, tests, evidence, and fixture DBs from the agent mount.
- Hidden verifier soundness, gold solutions, cheat-battery exploit-path execution.
- Model evaluation and measured long-horizon (≥15) pair-blind action counts.
- Symlink/junction escape on all platforms (not exercised beyond normal resolve checks).
- That a future RPC harness will wrap every substrate exception as `ToolError`.
- That workspace Python sources will ever become the executed repair surface (explicitly deferred).

---

## 15. Final verdict

### **PASS WITH FIXES — remediation required before Milestone 2 closure**

The twelve-tool interaction design, paired cutpoint diagnostics, public P1–P3 execution against live SQLite, candidate/active root separation, and most transition preconditions are **substantively present** and largely behave as intended under method-level attack. Milestone 1 remains green under `pytest tests`. The committed M2 receipt correctly points at source `8da69b57…` and matches live regeneration semantically after excluding timestamp, machine paths, and tip-vs-source commit labeling.

Closure should **not** proceed until at least:

1. Harden dispatch/RPC so evaluated agents never receive `_store` / `_profile` / fixture handles (**C1**).  
2. Bind public-pass credit to the active revision (or require re-run after deploy) so resume cannot close on unsafe reactivated config (**C2**).  
3. Normalize agent-visible failures to `ToolError` (**M1**).  
4. Rerun M1 from the M2 gate (or a composite verifier) and fix fragile `from conftest import` collection (**M2**).  
5. Tighten selector matching and deepen leak probes; document handle predictability and ceremonial code / deferred execution honestly (**M3–M7**).

### May Milestone 2 close?

**Not yet** — pending remediation of **C1** and **C2** (or an explicit user waiver that M2 closes as “API semantics only” with agent-mount and resume-credit holes labeled NOT VERIFIED).

### May later verifier work begin?

**Not as an automatic next stage.** After the user accepts this audit and either remediates or explicitly waives **C1**/**C2**/mount claims, Milestone 3 / hidden-verifier work may be approved. Do **not** start the hidden verifier, gold solutions, cheat battery, or model evaluation until that approval.

---

*Auditor note: adversarial probes were executed out-of-tree against temporary fixtures; repository implementation, tests, and committed receipts were not modified for this report. Live M2 receipt regeneration used a temp output path and did not overwrite `evidence/milestone-2-interaction-layer.json`.*
