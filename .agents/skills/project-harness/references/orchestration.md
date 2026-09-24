# Orchestration

Read this reference immediately before delegation. Use the fewest executors that provide real benefit.

## Decide whether to delegate

Delegate a concrete bounded subtask when it is sufficiently independent and parallel work or specialized review materially improves the result. Keep a task local when coordination would cost more than execution, when the next decision depends on its result, or when writes overlap without isolation.

Do not invent agents. If the host lacks delegation, execute sequentially and label self-review honestly.

## Task contract

Give each worker:

- a concrete outcome and why it matters;
- the minimum sufficient context and active requirements;
- inputs and sources;
- owned files or write area;
- actions and data it may access;
- acceptance checks and evidence expected;
- limits, dependencies, and stop conditions;
- notice that other work may exist and must not be reverted.

Use [the task contract template](../assets/templates/task-contract.md) when a durable contract helps. Do not assume a worker inherited the conversation or this Skill.

## Integrate

The primary executor owns the overall result and canonical state. Workers return artifacts, changes, checks, limitations, and open questions. Inspect actual changes, reconcile contracts, and verify interactions before acceptance. A confident summary is not evidence.

Parallelize only independent writes. Agree shared interfaces before implementation. Serialize or isolate overlapping areas. Workers submit proposals rather than concurrently replacing `.harness/state.json`.

When a retry fails for the same reason, change the cause, input, or method before retrying again. Escalate a real blocker instead of cycling workers.
