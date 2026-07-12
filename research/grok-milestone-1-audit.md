# Milestone 1 adversarial audit

**Auditor role:** falsify-by-default review of the paired substrate  
**Scope:** read-only; no implementation changes; no Milestone 2 work  
**Inputs:** `AGENTS.md`, research reports, `pyproject.toml`, `README.md`, `src/event_service_substrate/`, `tests/milestone_1/`, `evidence/milestone-1-substrate.json`

---

## 1. Executive verdict

### PASS WITH FIXES

The core Milestone 1 substrate claims largely hold under independent reproduction: deterministic roots, matched public workspaces, shared `r0`/`r1` lineage, distinct privileged histories, pause-gated `S0` restore with telemetry/audit append, and 11 passing tests. Fresh construction reproduces the receipt roots exactly.

Milestone 2 must **not** begin until the critical and major fixes below land. The current integrity language overstates what “signed” recovery proves, `recovery_is_valid()` accepts forged audit+mutation, and privileged identifiers encode member structure that will become agent-visible as soon as state tools exist.

---

## 2. Reproduction result

| Field | Value |
|---|---|
| Exact command | `.\.venv\Scripts\python.exe -m pytest tests\milestone_1 -q` |
| Exact result | `11 passed in 5.59s` (exit code 0) |
| Test count | 11 collected / 11 passed |
| Runtime | 5.59s wall; slowest call ~1.04s (`test_roots_are_deterministic...`) |
| Warnings | None from pytest. Separate audit scripts emitted one PowerShell/`python -c` `SyntaxWarning` unrelated to the package. |
| Receipt match | Fresh `build_fixture` roots for profiles `0` and `1` **byte-match** `evidence/milestone-1-substrate.json` `deterministic_roots`. Test command/count/outcome match the live run. |

---

## 3. Critical issues

### C1. “Signed” snapshots are publicly forgeable digests, not authenticating seals

`create_snapshot` / `snapshot_is_valid` define:

- `signed_root = digest("service-state-v1", payload)`
- `signature = digest("local-snapshot-signature-v1", payload)`

There is no secret key, HMAC, or external verifier identity. Any party that can write SQLite rows can insert a new snapshot of arbitrary service state that `snapshot_is_valid` accepts.

**Attack reproduced:** copy Instance A’s post-incident service document into Instance B as `S1` with recomputed digests → `snapshot_is_valid("S1")` is true → `restore("S1")` loads A’s journal (`evt-041-a` only) into B → `recovery_is_valid()` becomes true.

**Impact:** the receipt/README language of “signed S0 restoration” is stronger than the mechanism. Cross-member substitution of `S0` is currently a no-op because both `S0` payloads are identical by construction; substitution of *any later or forged* snapshot is not blocked.

### C2. `recovery_is_valid()` accepts direct mutation plus a forged audit entry

Bare deletion of journal/effects/keys and cursor reset makes `state_root == S0.signed_root` but `recovery_is_valid() == False` (tested). That is necessary but not sufficient.

**Attack reproduced:**

1. Delete service rows / reset cursor so `state_root == S0`.
2. Call `append_audit("snapshot_restore", s0_root, "attacker", tick)`.

Result: `audit_chain_valid() == True` and `recovery_is_valid() == True` without calling `restore_snapshot`.

**Impact:** Milestone 1 only rejects one named deletion pattern. It does **not** distinguish authorised restore from arbitrary state mutation. Any later verifier predicate that trusts `recovery_is_valid()` alone is unsound.

### C3. Receipt leak check is circular and hard-coded

`test_public_surface_and_process_metadata_do_not_leak_selector` asserts:

```python
assert receipt["leak_check"]["passed"] is True
```

against a static JSON file. No test regenerates the receipt from a live run. `leak_check.passed` can remain `true` forever while the implementation regresses.

**Impact:** the receipt’s leak section is not evidence; it is an unchecked claim mirrored by the suite.

---

## 4. Major issues

### M1. Privileged IDs encode member/causal structure (`evt-041-a` / `evt-041-b`)

Independent dump:

| Member | Journal event IDs | Effect provenance |
|---|---|---|
| A (`profile=0`) | `evt-041-a` | both effects from `evt-041-a` |
| B (`profile=1`) | `evt-041-a`, `evt-041-b` | one effect each |

Public surfaces do not contain these strings today. They live in SQLite and package source (`instance.py`). As soon as Milestone 2 exposes journal/effect selectors to the agent, the `-a`/`-b` suffix scheme is a **direct structural answer leak**: presence of `evt-041-b` classifies B; single `evt-041-a` classifies A.

This is currently an “unavoidable hidden-state difference that is accidentally named.” It must be neutralized before any agent-visible state tool lands.

### M2. `public_status()["attempt_budget"]` is hard-coded to `1`

It does not read `settings.toml` or deployment config. Editing the workspace config changes the recomputed config digest but leaves the public status field lying. `revision_diff()` is likewise a hard-coded string, not derived from revision artifacts.

### M3. Deployment / runtime mutations are outside `state_root`

`state_root` covers only `SERVICE_TABLES` (`journal`, `cursor`, `effects`, `intents`, `event_marks`, `command_keys`). Independent probes showed:

- flipping active deployment rows does **not** change `state_root`;
- advancing the fake clock does **not** change `state_root`;
- appending telemetry does **not** change `state_root`;
- editing effect amounts **does** change `state_root`.

So “canonical state” is narrower than “operational world.” That can be intentional, but then deployment health and intake/tick must be graded by other roots. Today `roots()` exposes `source/config/state/telemetry/audit/snapshot` with **no deployment root**.

### M4. Leak tests use a fixed token list, not independent enumeration

Forbidden tokens include phrases like `"instance a"`, `"idempotency"`, `"profile"`. They do **not** scan for `evt-041-a`, `cmd-041`, `occ-041`, `eff-041-*`, profile integers, or A/B root divergence side channels. Package source itself contains `profile` and `evt-041-a` (privileged builder code).

### M5. Snapshot restore does not require a valid prior audit chain

After corrupting `audit_chain.entry_hash`, `restore_snapshot` still succeeds. `recovery_is_valid()` then fails because `audit_chain_valid()` is false. Restore itself is therefore not gated on forensic integrity—only the post-hoc helper is.

### M6. Construction-order determinism is untested in-suite

Independent runs showed `A→B` vs `B→A` and triple rebuilds preserve roots. The pytest suite never constructs B before A, so this claim is **auditor-verified**, not **suite-enforced**.

---

## 5. Minor issues

### m1. Receipt `git_sha` is not `HEAD`

Receipt pins `5f14840…` with `git_sha_status: "tested-source-commit"`. Current `HEAD` is `ac3f1f8…` (`docs: align agent rules with milestone 1 audit stage`). Roots still match, so substrate fidelity is fine, but the receipt does not represent the full current tree tip.

### m2. `telemetry.seq` uses `AUTOINCREMENT`

Deterministic for clean construction order, but fragile if rows are deleted/reinserted. Prefer explicit monotonic seq assignment from the fake clock/controller.

### m3. `revision_diff()` cannot detect config drift

If `r0`/`r1` bytes diverge from the hard-coded diff story, public status still reports the canned text.

### m4. DB file sizes are equal despite different journal cardinality

`(service.sqlite3)` was `90112` bytes for both members in this environment. Size is not a leak today, but row-count differences (`journal` 1 vs 2) will be if exposed.

### m5. `AGENTS.md` still says research-stage / do not implement

Process docs lag the Milestone 1 implementation claim in `README.md`. Not a substrate defect, but evidence hygiene is inconsistent.

### m6. Schema adds `runtime_state` and `telemetry` beyond the spike design table list

Acceptable for M1, but documentation should state the actual schema as authoritative.

---

## 6. Determinism findings

| Check | Result |
|---|---|
| Same member → identical roots across rebuilds | **Pass** |
| Construction order A→B vs B→A | **Pass** (independent; not in pytest) |
| Repeated process constructions | **Pass** |
| Unicode / spaces in absolute path | **Pass** (roots unchanged) |
| Env vars `EVENT_SERVICE_MEMBER` / `fixture_profile` | **Pass** (no root effect) |
| Locale / cwd dependence in hashes | **Pass** under exercised probes; paths normalized with `as_posix()` |
| SQLite row ordering in canonical docs | **Pass** (`ORDER BY` all columns) |
| Wall-clock in package `*.py` | **Pass** (string scan in tests + review) |
| Receipt roots vs fresh run | **Pass** |

**Strongest determinism risk:** `AUTOINCREMENT` telemetry sequencing and any future non-ordered dict/filesystem iteration outside `canonical.py`. Current tree hashing sorts paths. No environment path bytes enter digests.

**Not a failure:** `timestamp` in the receipt is wall-clock metadata and is correctly excluded from canonical roots.

---

## 7. Public-surface equality findings

Independent enumeration of workspace files (SHA-256 per relative POSIX path) found **exact equality** for:

```text
service/contract.md
service/flow.py
service/runtime.py
service/settings.toml
service/store.py
```

Also equal across A/B:

- `public_bytes()`
- `public_status()` (including ticket, logs, canary, shared roots)
- `visible_logs()` / `VISIBLE_LOGS`
- `revision_diff()`
- source/config/telemetry/audit/snapshot roots

**Intentional privileged differences (not public):**

- `state` root
- journal cardinality and event IDs
- effect provenance
- command-key target event
- cursor committed seq (`1` vs `2`)

**Unintentional public issues:** none found in the agent-intended workspace. Hard-coded status fields are identical, so they do not create A/B divergence; they create truthfulness debt instead (M2).

---

## 8. Leakage findings

| Channel | Finding | Class |
|---|---|---|
| Public workspace bytes / filenames / comments | No A/B or causal-layer tokens from the suite list; independent scan also clean for `evt-041-*` | Clean |
| Ticket / normalized logs / status | Matched; no member label | Clean |
| Env / `sys.argv` | No `member_selector` / `fixture_profile` required at runtime | Clean for M1 |
| Package source (`build_fixture`, seeds) | Contains `profile`, `evt-041-a`, `evt-041-b`, effect IDs | Privileged builder leak; must stay non-agent-visible |
| SQLite contents | Member-discriminative IDs and counts | **Hidden-state difference**, currently privileged; **naming is accidental answer encoding** |
| DB filename / path layout | Neutral `service.sqlite3` | Clean |
| Canonical shared roots | Identical; no classification | Clean |
| Divergent `state` root | Distinguishes members if exposed raw | Expected privileged difference; must not appear in public status (currently excluded — good) |
| Receipt JSON | Labels `A`/`B` and prints divergent state roots | Human evidence only; must not be agent-mounted |
| Exception text | Pause/restore errors are neutral | Clean |

**Strongest leak risk:** `-a`/`-b` event/effect identifiers in durable state once Milestone 2 state inspection exists.

---

## 9. Snapshot attack results

| Attack | Result |
|---|---|
| Restore without pause | **Rejected** (`RuntimeError`) |
| Unknown snapshot ID | **Rejected** (`ValueError`) |
| Modify payload, keep old signature | `snapshot_is_valid` false; restore rejected |
| Modify signature only | invalid; restore rejected |
| Valid restore twice | Same restored state root; snapshot table root unchanged; audit root advances |
| Restore after unrelated effect insert | Clears mutation; returns to `S0` service state |
| Telemetry mutation / restore | Telemetry preserved and appended (`control` lines) |
| Audit-chain mutation then restore | Restore still runs; chain remains invalid; `recovery_is_valid` false |
| Substitute A `S0` into B | Trivial: payloads identical by design |
| Substitute A **incident** state as forged snapshot into B | **Succeeds** (C1) |
| Re-serialize payload without `sort_keys`, re-sign | Accepts; restore yields canonical empty state matching digest of sorted service doc |

**Verified positives:** pause gate, invalid signature/payload rejection, telemetry survival, audit append on success, repeated restore stability, `S0.created_tick=40` predates `accepted_tick>=41`.

**Integrity seal honesty:** local digest MAC with public domain strings only. Do not describe as cryptographic authenticity or cross-instance trust.

---

## 10. Canonical-root review

| Root | Includes | Excludes | Notes |
|---|---|---|---|
| `source` | Sorted public code files under `CODE_FILES` | `settings.toml`, DB, telemetry | Path-normalized; size+file digest |
| `config` | Workspace `settings.toml` bytes | Deployment table | Fixture caches digest at build |
| `state` | Service tables only | deployments, telemetry, audit, snapshots, runtime_state | Clock/intake/deploy edits invisible here |
| `telemetry` | `telemetry` rows ordered by all columns | — | AUTOINCREMENT seq included |
| `audit` | `audit_chain` | Whether resulting_root matches live state historically | Chain hash links entries |
| `snapshot` | `recovery_snapshots` rows including payload/signature | Live service tables | Unchanged when live effects mutate |

**Issues:**

- Omitted security-relevant live fields from `state`: active revision, intake, tick.
- No ambiguous string concatenation: digests use `domain + NUL + payload` and JSON with `sort_keys=True`.
- Roots can remain unchanged after meaningful operational mutation (deploy/tick/telemetry) — see M3.
- Shared equality of snapshot/audit/telemetry roots across A/B is correct for the matched public story; only `state` should diverge.

---

## 11. Test-quality review

Mapping approximate original M1 claim surface (~16 checks) onto 11 tests:

| Claim / check | Covered? | How / gap |
|---|---|---|
| Deterministic Python/SQLite substrate | Partial | Schema + roots tests; no multi-process isolation claim tested |
| Integer fake clock / transition costs | Yes | `test_fake_clock...` |
| Required persistence schema | Yes | Compares to `SCHEMA_TABLES` |
| Canonical hashing | Partial | Indirect via roots equality; no adversarial collision cases |
| Byte-identical public workspaces | Yes | Path set + bytes |
| Shared r0/r1 lineage + candidate | Yes | |
| Two privileged histories | Yes | Shape assertions |
| Matched ticket/log/symptom | Yes | Bundled into workspace test |
| Signed S0 restore | Partial | Happy path + pause; **no** signature-negative beyond missing ID; **no** forgery test |
| Telemetry/audit preservation | Yes | Bundled into restore test |
| Direct-deletion recovery rejection | Partial | Only bare delete; **misses forged audit bypass** |
| Public-surface leak checks | Partial | Fixed token list + circular receipt flag |
| No wall clock in substrate | Yes | |
| Determinism under order/path/env | **Missing** in suite | Auditor verified |
| S0 predates incident | **Missing** explicit assert | True in data (`40` vs `≥41`) |
| Receipt regeneration / root binding | **Missing** | Static JSON |
| Cross-member snapshot forgery | **Missing** | |
| Histories not reversed | Weak | Would fail if swapped profiles, but fixture order is fixed `0` then `1` |

**Bundling:** restore forensics, pause gate, and validity are one test. Public equality bundles files, ticket, logs, and `public_bytes`.

**Shared-helper blindness:** tests call `build_fixture` / `recovery_is_valid` / `public_bytes`—the same code paths as production. They would not catch a bug where helper and test both encode the same wrong invariant (forged recovery is the exhibit).

**Swap safety:** history-shape test would catch A/B reversal of profiles. Root-divergence test would not catch label swap if both profiles still diverge.

**Receipt generation:** not tested. Leak section trusts a boolean.

---

## 12. Receipt review

File: `evidence/milestone-1-substrate.json`

| Field | Assessment |
|---|---|
| `test.command` | Accurate vs README and live reproduction |
| `test.count` / `outcome` | Accurate for current suite; **static**, not derived by CI hook visible in-repo |
| `deterministic_roots` | **Match fresh run** for both members |
| `shared_equality_checks` | Consistent with live equality; not independently re-verified by automated receipt writer |
| `snapshot_restoration` | Plausible; not re-executed by receipt tooling in-repo |
| `timestamp` | Wall-clock metadata; correctly out of canonical roots |
| Privileged causal prose | Absent (good) |
| Member labels `A`/`B` | Present as receipt keys (acceptable for human evidence; not agent-safe) |
| `git_sha` | Pins substrate commit `5f14840…`, not current `HEAD` |
| Isolation claims | Does not claim container/OS isolation (good). Must not be read as stronger than local SQLite digests |

**Bottom line:** roots are trustworthy; process metadata is partially stale; leak booleans are not evidence.

---

## 13. Exact fixes required before Milestone 2

1. **Neutralize identifier encoding:** replace `-a`/`-b` suffixes with member-blind opaque IDs that do not classify the fixture from a single row dump. Keep histories semantically distinct without naming the answer.
2. **Either harden or demote recovery validity:**
   - Harden: bind restore audits to snapshot payload hash, actor capability, and preimage of restored tables; reject `append_audit` forgeries; or
   - Demote: document explicitly that `recovery_is_valid()` is a weak heuristic and must not be a Milestone 2 grader predicate until provenance is real.
3. **Correct “signed snapshot” language** in README/receipt/docs to “locally digested snapshot with public domain separation,” unless a real keyed MAC is added (still local-trust only without key isolation).
4. **Add negative tests:** payload/signature tamper, forged audit recovery bypass, forged cross-fixture snapshot install, S0 predates incident, construction order B→A, path/env determinism.
5. **Derive `attempt_budget` and revision diff from artifacts**, not literals.
6. **Stop circular receipt asserts:** generate receipt from pytest (or a small sealed script) in one command; commit regenerated JSON; assert roots by recomputation in-test rather than trusting `leak_check.passed`.
7. **Decide deployment/runtime grading:** add a deployment/runtime root or document that those fields are out of `state_root` and will be checked separately in the verifier.
8. **Keep package builder source and receipt out of any future agent mount.**

---

## 14. Claims that remain NOT VERIFIED

- Production or OS-level tamper isolation (not claimed strongly; still unverified).
- Cryptographic authenticity of snapshots (claim language overreached; mechanism unverified as signing).
- That `recovery_is_valid` distinguishes authorised recovery from arbitrary mutation (**falsified**).
- Suite-enforced order/path/env determinism (**auditor-verified only**).
- Receipt auto-derivation from CI (**absent**).
- Agent API non-leakage under state/log/trace tools (**Milestone 2 surface does not exist yet**).
- Hidden workload / oracle behavior (**out of Milestone 1 scope**).
- That public equality will survive once runtime mutates shared telemetry templates during interactive episodes.

---

## Summary

| Item | Value |
|---|---|
| **Verdict** | **PASS WITH FIXES** |
| **Test result** | `11 passed in 5.59s` |
| **Critical / major / minor** | **3 / 6 / 6** |
| **Strongest leak risk** | Privileged `evt-041-a` / `evt-041-b` (and related) ID encoding |
| **Strongest determinism risk** | `AUTOINCREMENT` telemetry seq + future unordered serialization |
| **May Milestone 2 begin?** | **No** — not until §13 items 1–6 are fixed and re-audited for the agent-visible boundary |
