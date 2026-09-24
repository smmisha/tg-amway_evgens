# Workflow

Use this reference when a project needs specification, design, planning, change control, or a return between lifecycle stages. Stages describe required outcomes. They do not require separate files, repeated user approval, or a full process for a small task.

## Stage gates

### 1. Sketch and clarify

Inspect all provided material first. Establish the intended result, recipient, format, current state, constraints, excluded scope, and unknowns that could change the next material decision. Separate facts, assumptions, decisions, and questions.

Ask independent blocking questions together. Ask a prerequisite before questions whose wording depends on its answer. Retain a nonblocking question with the decision it must precede. Continue safe independent work while a branch awaits input.

Advance when the nearest requirements can be stated without a hidden material assumption.

### 2. SPEC

Express each active requirement as an observable result with acceptance. Define the version boundary and exclusions. For managed work, assign stable IDs and statuses: `active`, `deferred`, `removed`, or `blocked`.

Do not silently add a feature because it seems useful. Show material impact before changing the agreed outcome. Optional commercial work is outside the active scope unless explicitly requested or enabled by project policy.

Advance when active requirements are testable and no unresolved contradiction blocks design.

### 3. Design / architecture

Define structure, interfaces, data ownership, dependencies, failure behavior, operational boundaries, and significant tradeoffs. Test a consequential assumption before building around it. Keep reversible implementation choices with the executor; take unresolved material product or visual choices to the user. A direction already set by the user or an applicable design system does not need renewed agreement.

Advance when a feasible path exists and critical unknowns are resolved or isolated.

### 4. Roadmap and tasks

Order demonstrable increments by dependency. Give the nearest task its inputs, outputs, owned files or area, permissions, acceptance, and checks. Keep distant work less detailed until earlier evidence can change it.

Advance when the next task can be executed without rediscovering scope.

### 5. Implementation

Create actual artifacts. Follow repository conventions, use existing components, and preserve unrelated changes. Verify meaningful increments. Do not label a plan, placeholder, or generated scaffold as implemented behavior.

Advance when the agreed result exists and is available for final verification.

### 6. Final verification

Check the active SPEC, integration among parts, and important user scenarios on the current snapshot. Inspect failures and fix their cause, update the requirement through an explicit decision, or disclose a real limitation. Never remove or weaken a check only to obtain a green status.

Advance when required current checks pass, necessary approvals exist, and unresolved limits are explicit.

### 7. Handover / launch

Provide the artifacts, usage or launch instructions, current evidence, and limitations. Perform publication, deployment, or external delivery only with adequate authority, then verify the actual effect. Separate technical readiness, release, receipt, external acceptance, and any professional approval.

## Change impact

When new information changes the work:

1. identify the affected requirements and decisions;
2. identify dependent artifacts, tasks, checks, sources, and operational safeguards;
3. update only those items and preserve independent results;
4. invalidate evidence whose explicit inputs changed;
5. record the reason and source of a material scope decision.

Do not rewrite historical requirements to resemble the implementation.

## Visual work

When appearance affects meaning, use, or acceptance, show an appropriate preview before expensive implementation if a material direction is still open. Label a concept image, static mockup, interactive prototype, and running result accurately. Obtain agreement only on unresolved material choices; use a direction already supplied by the user or an applicable design system. Then verify the real artifact across applicable sizes, text lengths, languages, and states.

## Scaling examples

- A small bug with a short, independent agent review remains `compact` when the fix and checks are recoverable from the files and conversation. Delegation alone does not justify project records.
- A project spanning sessions with dependent deliverables and separate owners uses `managed`: record active requirements, decisions, task ownership, evidence, and the next action so another session can resume without guessing.
- A publication with an uncertain external outcome uses `managed` even if the artifact is small. Record the intended effect and inspect the destination before retrying; a prepared upload is not proof of publication.
