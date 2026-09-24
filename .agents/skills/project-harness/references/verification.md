# Verification and freshness

Use this reference to define acceptance, record evidence, invalidate stale checks, evaluate changeable sources, or prepare release.

## Match evidence to the claim

Choose an observation capable of detecting the relevant failure. Source reading can support design understanding; it does not prove execution. A unit test covers its boundary; it does not prove an end-to-end scenario. A screenshot can support visual review; it does not prove hidden behavior. An old successful log does not cover a changed artifact.

Distinguish `planned`, `running`, `passed`, `failed`, `blocked`, `skipped`, `not_applicable`, and `stale`. A check is `passed` only after execution against an identified subject with method, environment, time, and evidence.

## Snapshot binding

For a local check, record explicit input paths and a snapshot fingerprint based on sorted `relative_path | byte_size | sha256` entries. Record material runtime, dependency, configuration, or deployment identity when the claim depends on them. Keep the human-readable product version separate.

After a change, mark a passed check `stale` when its explicit inputs intersect the changed inputs. Preserve a check only when its independence is explicit. Unknown dependency is handled conservatively. Stale optional evidence blocks only the claim that depends on it, not unrelated state operations.

The helper can verify hashes and declared dependencies. It cannot prove that the declared input list is semantically complete or that an evidence file is truthful.

## Requirement coverage

Before final readiness, each active requirement has an artifact or behavior and a current check, or a disclosed reason the observation is unavailable. Final verification covers integration and important user scenarios in addition to component checks.

Use truthful result states: `implemented`, `locally_verified`, `ready_for_review`, `ready_for_release`, `released`, and `externally_accepted`. Never infer a later state from an earlier one.

## External sources

For a material changeable claim, record the exact claim, source, entity or version, territory where relevant, event time, publication time, check time, place of use, and review trigger. Prefer applicable primary sources when current verification is required.

An unavailable, rejected, or unused source does not block an independent result. When an active claim depends on a stale or unavailable source, refresh it, replace it with an applicable source, or limit that claim. A newer source is not automatically more applicable. Missing data is not a negative fact.

Separate development research from a running product's refresh mechanism. A product that needs current data requires explicit sources, freshness limits, unavailable behavior, provenance, history, conflict handling, and update authority.
