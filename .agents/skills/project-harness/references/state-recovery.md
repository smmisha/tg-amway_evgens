# Managed state and recovery

Read this reference for multi-session work, durable coordination across executors, traceability, or an unfinished operation. Short safe work, including a bounded independent delegation, remains `compact` when its artifacts suffice for recovery and no other managed trigger applies; it does not need `.harness/`.

## Project-local records

Managed work uses `.harness/state.json` for current obligations and `.harness/events.jsonl` for the event log. Each successful helper `apply` also preserves the previous full state under `.harness/history/state-rev-<revision>.json`, so a removed or revised requirement can be inspected by content. Preserve these snapshots with the project; do not treat an event label as a reconstructable state. Evidence belongs under `.harness/evidence/` or in an authorized protected system. Project facts never belong in the installed Skill directory.

The current record includes the stage, active scope, active requirements and decisions, active tasks, current checks, open operations, active source dependencies, risks, permissions, blockers, and one next action. Detailed SPEC, architecture, roadmap, and logs remain separate files referenced from state.

History retains closed errors, removed requirements, cancelled attempts, and decision changes. A historical failure does not block release unless an active dependency still points to it.

## Single writer and proposals

Use one canonical-state writer. Workers return artifacts and proposed state changes under `.harness/proposals/` when durable proposals are useful. The writer reconciles them against the current revision.

The optional helper applies changes with expected-revision compare-and-swap, a local lock, validation, and atomic replacement. A revision conflict requires rereading and reconciliation. Do not force overwrite. Investigate a leftover lock through its owner and actual files; age alone does not prove abandonment.

## Operations

Use `not_started`, `in_progress`, `succeeded`, `failed`, `unknown`, and `cancelled`. A consequential operation also has a stable intended-effect ID. `failed` means a negative outcome was established. A timeout or lost response normally means `unknown` until the effect is inspected.

Before retrying `unknown`, use a read-only provider check, a receipt, or the same supported idempotency key. Otherwise keep the dependent branch blocked. A later confirmed attempt for the same intended effect may close the active blocker while the earlier failure remains in history.

## Recovery sequence

1. Reconcile state with files, processes, logs, evidence, deployed state, and external receipts that are actually accessible.
2. Classify every open operation from observations rather than the previous claim.
3. Preserve correct partial work and independent current checks.
4. Identify the smallest damaged or unfinished dependency set.
5. Continue from the first admissible step and rerun only affected checks plus justified integration checks.

If the effect cannot be established safely, stop that branch and return a continuation record. Do not reset the project to its last commit or delete partial data as a generic recovery action.

## Helper boundary

The helper validates record shape, explicit dependencies, hashes, revisions, and release gates. `release-check` requires final verification or handover stage, an explicit release-ready result, at least one active required requirement, and current passed coverage. It does not inspect a remote provider, terminate processes, retry an operation, prove evidence truth, or authorize release.
