#!/usr/bin/env python3
"""Optional standard-library helper for Project Harness managed state."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "2.0"
STAGES = {
    "sketch_clarify",
    "spec",
    "design",
    "roadmap_tasks",
    "implementation",
    "verification",
    "handover_launch",
}
RESULT_STATUSES = {
    "in_progress",
    "blocked",
    "implemented",
    "locally_verified",
    "ready_for_review",
    "ready_for_release",
    "released",
    "externally_accepted",
}
CHECK_STATUSES = {
    "planned",
    "running",
    "passed",
    "failed",
    "blocked",
    "skipped",
    "not_applicable",
    "stale",
}
OPERATION_STATUSES = {
    "not_started",
    "in_progress",
    "succeeded",
    "failed",
    "unknown",
    "cancelled",
}
COLLECTION_PREFIXES = {
    "requirements": "REQ-",
    "decisions": "DEC-",
    "tasks": "TASK-",
    "sources": "SRC-",
    "risks": "RSK-",
    "permissions": "PERM-",
    "blockers": "BLK-",
}
CHECK_PREFIX = "CHK-"
OPERATION_PREFIX = "OP-"


class HarnessError(RuntimeError):
    """Base error for invalid input, paths, or local I/O."""


class ConflictError(HarnessError):
    """Raised for existing state, locks, or revision conflicts."""


class ValidationError(HarnessError):
    """Raised when a state candidate violates computed invariants."""

    def __init__(self, issues: list[str]):
        super().__init__("; ".join(issues))
        self.issues = issues


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:40] or "project"


def new_state(name: str, skill_version: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_version": skill_version,
        "project_id": f"PROJECT-{_slug(name)}-{uuid.uuid4().hex[:8]}",
        "revision": 0,
        "updated_at": utc_now(),
        "depth": "managed",
        "stage": "sketch_clarify",
        "result_status": "in_progress",
        "capabilities": {
            "files": "available",
            "execution": "available",
            "network": "unknown",
            "visual": "unknown",
            "subagents": "unknown",
            "connectors": "unknown",
        },
        "scope": {"outcome": name, "exclusions": [], "artifact_refs": []},
        "requirements": {"active": []},
        "decisions": {"active": []},
        "tasks": {"active": []},
        "checks": {"current": []},
        "operations": {"open": []},
        "sources": {"active": []},
        "risks": {"active": []},
        "permissions": {"active": []},
        "blockers": {"active": []},
        "next_action": "Reconcile the requested outcome and active requirements.",
    }


def _is_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _ids(items: object, label: str, prefix: str, issues: list[str]) -> set[str]:
    result: set[str] = set()
    if not isinstance(items, list):
        issues.append(f"{label} must be a list")
        return result
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f"{label}[{index}] must be an object")
            continue
        value = item.get("id")
        if not isinstance(value, str) or not value.startswith(prefix):
            issues.append(f"{label}[{index}] ID must start with {prefix}")
            continue
        if value in result:
            issues.append(f"duplicate active ID: {value}")
        result.add(value)
    return result


CHECK_LIST_FIELDS = ("requirement_ids", "task_ids", "input_paths", "evidence_refs", "invalidated_by")
CHECK_ID_PATTERN_FIELDS = {
    "requirement_ids": r"REQ-[A-Za-z0-9._-]+",
    "task_ids": r"TASK-[A-Za-z0-9._-]+",
}
CHECK_ALLOWED_FIELDS = {
    "id", "status", "required", "requirement_ids", "task_ids", "method", "subject",
    "input_paths", "snapshot_fingerprint", "environment", "executed_at", "evidence_refs",
    "invalidated_by", "extensions",
}


def _check_issues(check: dict[str, Any], known_requirements: set[str], known_tasks: set[str]) -> list[str]:
    issues: list[str] = []
    check_id = check.get("id", "<missing-check-id>")
    if not isinstance(check_id, str) or not re.fullmatch(rf"{CHECK_PREFIX}[A-Za-z0-9._-]+", check_id):
        issues.append(f"check ID must match {CHECK_PREFIX}[A-Za-z0-9._-]+: {check_id}")
    unexpected = sorted(set(check) - CHECK_ALLOWED_FIELDS)
    if unexpected:
        issues.append(f"{check_id} has unexpected fields: {', '.join(unexpected)}")
    if "extensions" in check and not isinstance(check["extensions"], dict):
        issues.append(f"{check_id} extensions must be an object")
    status = check.get("status")
    if not isinstance(status, str) or status not in CHECK_STATUSES:
        issues.append(f"unsupported check status for {check_id}: {status}")
    if not isinstance(check.get("required"), bool):
        issues.append(f"{check_id} requires a boolean 'required' field")
    if not isinstance(check.get("subject"), str) or not check.get("subject"):
        issues.append(f"{check_id} requires a non-empty 'subject' field")
    if not isinstance(check.get("method"), str):
        issues.append(f"{check_id} requires a string 'method' field")
    environment = check.get("environment")
    if not isinstance(environment, dict):
        issues.append(f"{check_id} requires an 'environment' object")
    elif any(
        not isinstance(key, str) or not (value is None or isinstance(value, (str, int, float, bool)))
        for key, value in environment.items()
    ):
        issues.append(f"{check_id} environment values must be a string, number, boolean, or null")
    for field in CHECK_LIST_FIELDS:
        value = check.get(field)
        if not isinstance(value, list):
            issues.append(f"{check_id} requires a list '{field}' field")
            continue
        pattern = CHECK_ID_PATTERN_FIELDS.get(field)
        if pattern is not None:
            bad_items = [item for item in value if not isinstance(item, str) or not re.fullmatch(pattern, item)]
            if bad_items:
                issues.append(f"{check_id} {field} items must match {pattern}")
        else:
            bad_items = [item for item in value if not isinstance(item, str) or not item]
            if bad_items:
                issues.append(f"{check_id} {field} items must be non-empty strings")
        if not bad_items and len(value) != len(set(value)):
            issues.append(f"{check_id} {field} must not contain duplicate items")
    if "snapshot_fingerprint" not in check:
        issues.append(f"{check_id} is missing 'snapshot_fingerprint' (use null if not yet known)")
    fingerprint = check.get("snapshot_fingerprint")
    if fingerprint is not None and not (
        isinstance(fingerprint, str) and re.fullmatch(r"[0-9a-f]{64}", fingerprint)
    ):
        issues.append(f"{check_id} snapshot_fingerprint must be null or a 64-character hex string")
    if "executed_at" not in check:
        issues.append(f"{check_id} is missing 'executed_at' (use null if not yet known)")
    executed_at = check.get("executed_at")
    if executed_at is not None and not _is_datetime(executed_at):
        issues.append(f"{check_id} executed_at must be null or a timezone-aware timestamp")
    for field, known_ids, label in (
        ("requirement_ids", known_requirements, "requirement"),
        ("task_ids", known_tasks, "task"),
    ):
        references = check.get(field)
        if not isinstance(references, list):
            continue
        for reference in references:
            if not isinstance(reference, str) or not re.fullmatch(CHECK_ID_PATTERN_FIELDS[field], reference):
                continue
            if reference not in known_ids:
                issues.append(f"{check_id} references unknown {label}: {reference}")
    if status == "passed":
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            issues.append(f"passed check {check_id} requires a current fingerprint")
        if not check.get("method"):
            issues.append(f"passed check {check_id} requires a method")
        if not _is_datetime(executed_at):
            issues.append(f"passed check {check_id} requires timezone-aware executed_at")
        if not check.get("evidence_refs"):
            issues.append(f"passed check {check_id} requires evidence")
    return issues


def validate_state(state: object) -> list[str]:
    if not isinstance(state, dict):
        return ["state must be an object"]
    issues: list[str] = []
    required = {
        "schema_version", "skill_version", "project_id", "revision", "updated_at", "depth",
        "stage", "result_status", "capabilities", "scope", "requirements", "decisions",
        "tasks", "checks", "operations", "sources", "risks", "permissions", "blockers",
        "next_action",
    }
    missing = sorted(required.difference(state))
    issues.extend(f"missing top-level field: {field}" for field in missing)
    unexpected = sorted(set(state).difference(required | {"extensions", "legacy"}))
    issues.extend(f"unexpected top-level field: {field}" for field in unexpected)
    for optional_field in ("extensions", "legacy"):
        if optional_field in state and not isinstance(state[optional_field], dict):
            issues.append(f"{optional_field} must be an object")
    if missing:
        return issues
    if state.get("schema_version") != SCHEMA_VERSION:
        issues.append(f"unsupported schema_version: {state.get('schema_version')}")
    if not isinstance(state.get("skill_version"), str) or not state["skill_version"]:
        issues.append("skill_version must be a non-empty string")
    if not isinstance(state.get("project_id"), str) or not re.fullmatch(r"PROJECT-[A-Za-z0-9._-]+", state["project_id"]):
        issues.append("project_id must match PROJECT-[A-Za-z0-9._-]+")
    if type(state.get("revision")) is not int or state["revision"] < 0:
        issues.append("revision must be a non-negative integer")
    if not _is_datetime(state.get("updated_at")):
        issues.append("updated_at must be timezone-aware ISO 8601")
    if not isinstance(state.get("depth"), str) or state["depth"] not in {"compact", "managed"}:
        issues.append(f"unsupported depth: {state.get('depth')}")
    if not isinstance(state.get("stage"), str) or state["stage"] not in STAGES:
        issues.append(f"unsupported stage: {state.get('stage')}")
    if not isinstance(state.get("result_status"), str) or state["result_status"] not in RESULT_STATUSES:
        issues.append(f"unsupported result_status: {state.get('result_status')}")
    capabilities = state.get("capabilities")
    if not isinstance(capabilities, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        or value not in {"unknown", "available", "unavailable"}
        for key, value in capabilities.items()
    ):
        issues.append("capabilities must be an object of availability values")

    active_ids: set[str] = set()
    collection_ids: dict[str, set[str]] = {}
    for name, prefix in COLLECTION_PREFIXES.items():
        container = state.get(name)
        if not isinstance(container, dict) or set(container).difference({"active"}):
            issues.append(f"{name} must contain only active")
            items: object = []
        else:
            items = container.get("active")
        ids = _ids(items, f"{name}.active", prefix, issues)
        duplicates = active_ids.intersection(ids)
        issues.extend(f"duplicate active ID: {value}" for value in sorted(duplicates))
        active_ids.update(ids)
        collection_ids[name] = ids

    checks_container = state.get("checks")
    if isinstance(checks_container, dict) and set(checks_container).difference({"current"}):
        issues.append("checks must contain only current")
    checks = checks_container.get("current") if isinstance(checks_container, dict) else None
    check_ids = _ids(checks, "checks.current", CHECK_PREFIX, issues)
    if isinstance(checks, list):
        for check in checks:
            if isinstance(check, dict):
                issues.extend(
                    _check_issues(check, collection_ids.get("requirements", set()), collection_ids.get("tasks", set()))
                )

    operations_container = state.get("operations")
    if isinstance(operations_container, dict) and set(operations_container).difference({"open"}):
        issues.append("operations must contain only open")
    operations = operations_container.get("open") if isinstance(operations_container, dict) else None
    operation_ids = _ids(operations, "operations.open", OPERATION_PREFIX, issues)
    if isinstance(operations, list):
        for operation in operations:
            if not isinstance(operation, dict):
                continue
            operation_id = operation.get("id", "<missing-operation-id>")
            status = operation.get("status")
            if not isinstance(status, str) or status not in OPERATION_STATUSES:
                issues.append(f"unsupported operation status for {operation_id}: {status}")
            if status == "unknown" and not operation.get("intended_effect_id"):
                issues.append(f"unknown operation {operation_id} requires intended_effect_id")
            task_id = operation.get("task_id")
            if task_id is not None and (
                not isinstance(task_id, str) or task_id not in collection_ids.get("tasks", set())
            ):
                issues.append(f"{operation_id} references unknown task: {task_id}")

    duplicates = active_ids.intersection(check_ids | operation_ids) | check_ids.intersection(operation_ids)
    issues.extend(f"duplicate active ID: {value}" for value in sorted(duplicates))

    scope = state.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("outcome"), str):
        issues.append("scope.outcome must be a string")
    elif set(scope) != {"outcome", "exclusions", "artifact_refs"} or any(
        not isinstance(scope.get(field), list)
        or any(not isinstance(item, str) or (field == "artifact_refs" and not item) for item in scope[field])
        or len(scope[field]) != len(set(scope[field]))
        for field in ("exclusions", "artifact_refs")
    ):
        issues.append("scope must contain unique string exclusions and artifact_refs")
    if not isinstance(state.get("next_action"), str):
        issues.append("next_action must be a string")
    return sorted(set(issues))


def _normalise_input_path(root: Path, raw: str) -> tuple[str, Path]:
    if not isinstance(raw, str) or not raw.strip():
        raise HarnessError("snapshot paths must be non-empty strings")
    root = _root(root)
    portable = raw.replace("\\", "/")
    parts = portable.split("/")
    if Path(raw).is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise HarnessError(f"unsafe snapshot path: {raw}")
    lexical = root.joinpath(*parts)
    cursor = root
    for part in parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise HarnessError(f"snapshot path must not contain symlinks: {raw}")
    try:
        resolved = lexical.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HarnessError(f"snapshot file does not exist: {raw}") from exc
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise HarnessError(f"snapshot path is not a regular file inside root: {raw}")
    return resolved.relative_to(root).as_posix(), resolved


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_snapshot_manifest(root: Path, input_paths: Iterable[str]) -> list[str]:
    files: dict[str, Path] = {}
    for raw in input_paths:
        relative, path = _normalise_input_path(root, raw)
        files[relative] = path
    if not files:
        raise HarnessError("snapshot requires at least one input file")
    return [
        f"{relative} | {path.stat().st_size} | {_sha256_file(path)}"
        for relative, path in sorted(files.items())
    ]


def snapshot_fingerprint(root: Path, input_paths: Iterable[str]) -> str:
    manifest = build_snapshot_manifest(root, input_paths)
    canonical = ("\n".join(manifest) + "\n").encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _paths_overlap(first: str, second: str) -> bool:
    first = first.replace("\\", "/").strip("/")
    second = second.replace("\\", "/").strip("/")
    return first == second or first.startswith(second + "/") or second.startswith(first + "/")


def invalidate_checks(
    checks: Iterable[dict[str, Any]], changed_paths: Iterable[str], reason: str
) -> list[dict[str, Any]]:
    changed = [path.replace("\\", "/").strip("/") for path in changed_paths]
    result = copy.deepcopy(list(checks))
    for check in result:
        if check.get("status") != "passed":
            continue
        inputs = check.get("input_paths", [])
        if any(_paths_overlap(item, changed_item) for item in inputs for changed_item in changed):
            check["status"] = "stale"
            invalidated = check.setdefault("invalidated_by", [])
            if reason not in invalidated:
                invalidated.append(reason)
    return result


def operation_retry_allowed(
    operation: dict[str, Any], *, observed_receipt: str | None = None, idempotency_key: str | None = None
) -> bool:
    if operation.get("status") != "unknown":
        return True
    if observed_receipt:
        return True
    stored_key = operation.get("idempotency_key")
    return bool(stored_key and idempotency_key and stored_key == idempotency_key)


def resolve_effect_blockers(state: dict[str, Any], intended_effect_id: str) -> list[str]:
    blockers = state.get("blockers", {}).get("active", [])
    closed = [
        blocker.get("id")
        for blocker in blockers
        if blocker.get("intended_effect_id") == intended_effect_id
    ]
    state["blockers"]["active"] = [
        blocker
        for blocker in blockers
        if blocker.get("intended_effect_id") != intended_effect_id
    ]
    return [value for value in closed if isinstance(value, str)]


def recovery_summary(state: dict[str, Any]) -> dict[str, Any]:
    operations = state.get("operations", {}).get("open", [])
    return {
        "reconcile": [
            "project files and artifact fingerprints",
            "running processes and local logs",
            "external receipts or provider state for open effects",
        ],
        "preserve_artifacts": list(state.get("scope", {}).get("artifact_refs", [])),
        "open_operations": [item.get("id") for item in operations],
        "unknown_effects": [item.get("id") for item in operations if item.get("status") == "unknown"],
        "active_blockers": [
            item.get("id") for item in state.get("blockers", {}).get("active", [])
        ],
        "next_action": state.get("next_action"),
    }


def release_issues(state: dict[str, Any], root: Path | None = None) -> list[str]:
    issues = validate_state(state)
    if issues:
        return [f"state invalid: {issue}" for issue in issues]
    if state["stage"] not in {"verification", "handover_launch"}:
        issues.append("release requires final verification or handover stage")
    if state["result_status"] not in {"ready_for_release", "released", "externally_accepted"}:
        issues.append("result is not marked ready for release")
    requirements = {
        item["id"]: item
        for item in state["requirements"]["active"]
        if item.get("required", True)
    }
    if not requirements:
        issues.append("release requires at least one active required requirement")
    covered: set[str] = set()
    for check in state["checks"]["current"]:
        if check.get("required") and check.get("status") not in {"passed", "not_applicable"}:
            issues.append(
                f"required check is not passed: {check.get('id')} ({check.get('status')})"
            )
        if check.get("status") == "passed":
            if root is not None:
                try:
                    current_fingerprint = snapshot_fingerprint(root, check.get("input_paths", []))
                except HarnessError as exc:
                    issues.append(f"cannot identify current subject for {check.get('id')}: {exc}")
                    continue
                if current_fingerprint != check.get("snapshot_fingerprint"):
                    issues.append(f"snapshot fingerprint is stale for check: {check.get('id')}")
                    continue
            covered.update(check.get("requirement_ids", []))
    for requirement_id in sorted(set(requirements).difference(covered)):
        issues.append(f"active requirement lacks a current passed check: {requirement_id}")

    for operation in state["operations"]["open"]:
        issues.append(
            f"open operation blocks release: {operation.get('id')} ({operation.get('status')})"
        )
    for blocker in state["blockers"]["active"]:
        issues.append(f"active blocker: {blocker.get('id')}")

    active_requirement_ids = set(requirements)
    for source in state["sources"]["active"]:
        used_by = set(source.get("used_by", []))
        if used_by.intersection(active_requirement_ids) and source.get("status") not in {
            "verified",
            "not_applicable",
        }:
            issues.append(
                f"active source dependency is not verified: {source.get('id')} ({source.get('status')})"
            )
    for permission in state["permissions"]["active"]:
        if permission.get("required", True) and permission.get("status") not in {
            "granted",
            "not_applicable",
        }:
            issues.append(f"required permission is not granted: {permission.get('id')}")
    return sorted(set(issues))


def upsert_check(state: dict[str, Any], check: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    check_id = check.get("id")
    if not isinstance(check_id, str) or not check_id.startswith(CHECK_PREFIX):
        raise ValidationError([f"check ID must start with {CHECK_PREFIX}"])
    current = updated["checks"]["current"]
    current[:] = [item for item in current if item.get("id") != check_id]
    current.append(copy.deepcopy(check))
    issues = validate_state(updated)
    if issues:
        raise ValidationError(issues)
    return updated


def upsert_operation(state: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    operation_id = operation.get("id")
    if not isinstance(operation_id, str) or not operation_id.startswith(OPERATION_PREFIX):
        raise ValidationError([f"operation ID must start with {OPERATION_PREFIX}"])
    status = operation.get("status")
    if not isinstance(status, str) or status not in OPERATION_STATUSES:
        raise ValidationError([f"unsupported operation status for {operation_id}: {status}"])
    intended_effect_id = operation.get("intended_effect_id")
    if status == "unknown" and not intended_effect_id:
        raise ValidationError([f"unknown operation {operation_id} requires intended_effect_id"])
    opened = updated["operations"]["open"]
    opened[:] = [item for item in opened if item.get("id") != operation_id]
    if status in {"not_started", "in_progress", "unknown"}:
        opened.append(copy.deepcopy(operation))
    elif status == "failed" and intended_effect_id:
        blocker_id = f"BLK-{operation_id}"
        blockers = updated["blockers"]["active"]
        if not any(item.get("id") == blocker_id for item in blockers):
            blockers.append(
                {
                    "id": blocker_id,
                    "intended_effect_id": intended_effect_id,
                    "reason": f"Operation {operation_id} failed",
                }
            )
    elif status == "succeeded" and intended_effect_id:
        resolve_effect_blockers(updated, intended_effect_id)
    issues = validate_state(updated)
    if issues:
        raise ValidationError(issues)
    return updated


def _root(root: Path) -> Path:
    try:
        resolved = root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HarnessError(f"project root does not exist: {root}") from exc
    if not resolved.is_dir():
        raise HarnessError(f"project root is not a directory: {resolved}")
    return resolved


def _harness_dir(root: Path) -> Path:
    root = _root(root)
    path = root / ".harness"
    if path.exists() and path.is_symlink():
        raise HarnessError(".harness must not be a symlink")
    return path


def _write_json_atomic(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def _event(kind: str, actor: str, reason: str, subject_id: str | None = None) -> dict[str, Any]:
    return {
        "event_id": f"EVT-{uuid.uuid4().hex}",
        "recorded_at": utc_now(),
        "actor": actor,
        "kind": kind,
        "subject_id": subject_id,
        "intended_effect_id": None,
        "previous_status": None,
        "new_status": None,
        "reason": reason,
        "references": [],
    }


def init_project(root: Path, name: str, skill_version: str) -> Path:
    harness_dir = _harness_dir(root)
    state_path = harness_dir / "state.json"
    if state_path.exists():
        raise ConflictError(f"managed state already exists: {state_path}")
    harness_dir.mkdir(parents=True, exist_ok=True)
    (harness_dir / "evidence").mkdir(exist_ok=True)
    (harness_dir / "proposals").mkdir(exist_ok=True)
    state = new_state(name, skill_version)
    issues = validate_state(state)
    if issues:
        raise ValidationError(issues)
    _write_json_atomic(state_path, state)
    events_path = harness_dir / "events.jsonl"
    events_path.touch(exist_ok=False)
    _append_event(events_path, _event("project_initialized", "helper", "Created managed state", state["project_id"]))
    return state_path


def load_state(root: Path) -> dict[str, Any]:
    state_path = _harness_dir(root) / "state.json"
    try:
        value = json.loads(state_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise HarnessError(f"managed state does not exist: {state_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"cannot read managed state: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(["state must be an object"])
    return value


def status_summary(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": state.get("project_id"),
        "revision": state.get("revision"),
        "stage": state.get("stage"),
        "result_status": state.get("result_status"),
        "active_blockers": [item.get("id") for item in state.get("blockers", {}).get("active", [])],
        "open_operations": [item.get("id") for item in state.get("operations", {}).get("open", [])],
        "next_action": state.get("next_action"),
    }


def acquire_lock(root: Path, owner: str) -> str:
    harness_dir = _harness_dir(root)
    if not harness_dir.is_dir():
        raise HarnessError("managed state is not initialized")
    lock_path = harness_dir / ".lock"
    token = uuid.uuid4().hex
    payload = {
        "owner": owner,
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "created_at": utc_now(),
        "nonce": token,
    }
    try:
        with lock_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except FileExistsError as exc:
        raise ConflictError(f"state lock already exists: {lock_path}") from exc
    return token


def release_lock(root: Path, token: str) -> None:
    lock_path = _harness_dir(root) / ".lock"
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConflictError("state lock disappeared before release") from exc
    if payload.get("nonce") != token:
        raise ConflictError("state lock belongs to another writer")
    lock_path.unlink()


def apply_candidate(
    root: Path,
    candidate: dict[str, Any],
    expected_revision: int,
    actor: str,
    event_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = acquire_lock(root, actor)
    try:
        current = load_state(root)
        current_revision = current.get("revision")
        if current_revision != expected_revision:
            raise ConflictError(
                f"revision conflict: expected {expected_revision}, current {current_revision}"
            )
        if candidate.get("revision") != expected_revision:
            raise ConflictError(
                f"candidate revision {candidate.get('revision')} does not match expected {expected_revision}"
            )
        updated = copy.deepcopy(candidate)
        updated["revision"] = expected_revision + 1
        updated["updated_at"] = utc_now()
        issues = validate_state(updated)
        if issues:
            raise ValidationError(issues)
        harness_dir = _harness_dir(root)
        history_dir = harness_dir / "history"
        if history_dir.is_symlink():
            raise HarnessError(".harness/history must not be a symlink")
        history_path = history_dir / f"state-rev-{current_revision:08d}.json"
        if history_path.is_symlink():
            raise HarnessError(f"history snapshot must not be a symlink: {history_path}")
        if history_path.exists():
            if json.loads(history_path.read_text(encoding="utf-8")) != current:
                raise ConflictError(f"history snapshot differs from current revision: {history_path}")
        else:
            _write_json_atomic(history_path, current)
        _write_json_atomic(harness_dir / "state.json", updated)
        event = _event(
            "state_applied",
            actor,
            f"Applied state revision {updated['revision']}",
            updated["project_id"],
        )
        event["previous_status"] = str(current_revision)
        event["new_status"] = str(updated["revision"])
        if event_details:
            for key in (
                "kind",
                "subject_id",
                "intended_effect_id",
                "previous_status",
                "new_status",
                "reason",
                "references",
            ):
                if key in event_details:
                    event[key] = event_details[key]
        try:
            _append_event(harness_dir / "events.jsonl", event)
        except OSError as exc:
            _write_json_atomic(harness_dir / f"event-recovery-{event['event_id']}.json", event)
            raise HarnessError(f"state changed but event append failed; recovery marker written: {exc}") from exc
        return updated
    finally:
        release_lock(root, token)


def _load_candidate(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HarnessError(f"cannot read candidate: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(["candidate must be an object"])
    return value


def record_check(
    root: Path, check: dict[str, Any], expected_revision: int, actor: str
) -> dict[str, Any]:
    current = load_state(root)
    candidate = upsert_check(current, check)
    return apply_candidate(
        root,
        candidate,
        expected_revision,
        actor,
        {
            "kind": "check_recorded",
            "subject_id": check["id"],
            "new_status": check.get("status"),
            "reason": f"Recorded check {check['id']}",
            "references": list(check.get("evidence_refs", [])),
        },
    )


def record_operation(
    root: Path, operation: dict[str, Any], expected_revision: int, actor: str
) -> dict[str, Any]:
    current = load_state(root)
    previous = next(
        (item.get("status") for item in current["operations"]["open"] if item.get("id") == operation.get("id")),
        None,
    )
    candidate = upsert_operation(current, operation)
    return apply_candidate(
        root,
        candidate,
        expected_revision,
        actor,
        {
            "kind": "operation_recorded",
            "subject_id": operation["id"],
            "intended_effect_id": operation.get("intended_effect_id"),
            "previous_status": previous,
            "new_status": operation.get("status"),
            "reason": f"Recorded operation {operation['id']}",
            "references": list(operation.get("observations", [])),
        },
    )


def _migrated_id(prefix: str, value: object) -> str:
    raw = str(value or uuid.uuid4().hex[:8])
    if raw.startswith(prefix):
        return raw
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._") or uuid.uuid4().hex[:8]
    return f"{prefix}{safe}"


def _convert_v1_state(v1: dict[str, Any], target_version: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if v1.get("schema_version") != 1:
        raise HarnessError(f"unsupported v1 schema_version: {v1.get('schema_version')}")
    project = v1.get("project")
    scope = v1.get("scope")
    if not isinstance(project, dict) or not isinstance(scope, dict):
        raise HarnessError("v1 project and scope must be objects")
    name = project.get("name")
    if not isinstance(name, str) or not name.strip():
        raise HarnessError("v1 project.name must be non-empty")

    state = new_state(name, target_version)
    stage_map = {
        "sketches": "sketch_clarify",
        "clarification": "sketch_clarify",
        "spec": "spec",
        "design": "design",
        "roadmap": "roadmap_tasks",
        "tasks": "roadmap_tasks",
        "implementation": "implementation",
        "verification": "verification",
        "handover": "handover_launch",
    }
    state["stage"] = stage_map.get(project.get("stage"), "sketch_clarify")
    state["capabilities"].update(
        {
            key: value
            for key, value in v1.get("capabilities", {}).items()
            if value in {"unknown", "available", "unavailable"}
        }
    )
    state["scope"] = {
        "outcome": str(scope.get("outcome") or name),
        "exclusions": [str(item) for item in scope.get("exclusions", []) if isinstance(item, str)],
        "artifact_refs": [],
    }
    state["next_action"] = str(v1.get("next_action") or "Reconcile migrated state.")

    events: list[dict[str, Any]] = []
    requirement_ids: set[str] = set()
    for item in v1.get("requirements", []):
        if not isinstance(item, dict):
            continue
        requirement = copy.deepcopy(item)
        requirement["id"] = _migrated_id("REQ-", item.get("id"))
        requirement.setdefault("status", "active")
        state["requirements"]["active"].append(requirement)
        requirement_ids.add(requirement["id"])

    task_id_map: dict[str, str] = {}
    active_task_ids: set[str] = set()
    for item in v1.get("tasks", []):
        if not isinstance(item, dict):
            continue
        old_id = str(item.get("id") or "")
        new_id = _migrated_id("TASK-", old_id)
        task_id_map[old_id] = new_id
        if item.get("status") in {"verified", "cancelled"}:
            event = _event("v1_task_archived", "migration", f"Archived v1 task {old_id}", new_id)
            event["previous_status"] = item.get("status")
            events.append(event)
            continue
        task = copy.deepcopy(item)
        task["id"] = new_id
        task["requirement_ids"] = [
            _migrated_id("REQ-", value)
            for value in item.get("requirement_ids", [])
            if _migrated_id("REQ-", value) in requirement_ids
        ]
        state["tasks"]["active"].append(task)
        active_task_ids.add(new_id)

    for item in v1.get("checks", []):
        if not isinstance(item, dict):
            continue
        old_status = item.get("status")
        fingerprint = item.get("snapshot_fingerprint")
        bound = isinstance(fingerprint, str) and bool(re.fullmatch(r"[0-9a-f]{64}", fingerprint))
        status = old_status if old_status in CHECK_STATUSES else "planned"
        invalidated_by: list[str] = []
        if status == "passed" and not bound:
            status = "stale"
            invalidated_by.append("migration-unbound-v1-evidence")
        evidence_refs = [
            value.get("path")
            for value in item.get("evidence", [])
            if isinstance(value, dict) and isinstance(value.get("path"), str)
        ]
        check = {
            "id": _migrated_id("CHK-", item.get("id")),
            "status": status,
            "required": bool(item.get("required", True)),
            "requirement_ids": [
                _migrated_id("REQ-", value)
                for value in item.get("requirement_ids", [])
                if _migrated_id("REQ-", value) in requirement_ids
            ],
            "task_ids": [
                task_id_map[str(value)]
                for value in item.get("task_ids", [])
                if str(value) in task_id_map and task_id_map[str(value)] in active_task_ids
            ],
            "method": str(item.get("method") or ""),
            "subject": str(item.get("version") or project.get("version") or "v1 subject"),
            "input_paths": list(item.get("input_paths", [])) if bound else [],
            "snapshot_fingerprint": fingerprint if bound else None,
            "environment": {"migrated_from": "1"},
            "executed_at": item.get("executed_at"),
            "evidence_refs": evidence_refs,
            "invalidated_by": invalidated_by,
        }
        state["checks"]["current"].append(check)

    operations = [item for item in v1.get("operations", []) if isinstance(item, dict)]
    successful_effects = {
        f"EFF-{item.get('task_id') or item.get('id')}"
        for item in operations
        if item.get("status") in {"completed", "succeeded"}
    }
    status_map = {
        "planned": "not_started",
        "running": "in_progress",
        "partial": "unknown",
        "unknown": "unknown",
        "completed": "succeeded",
        "failed": "failed",
        "cancelled": "cancelled",
    }
    for item in operations:
        operation_id = _migrated_id("OP-", item.get("id"))
        effect_id = f"EFF-{item.get('task_id') or item.get('id')}"
        status = status_map.get(item.get("status"), "unknown")
        operation = {
            "id": operation_id,
            "status": status,
            "intended_effect_id": effect_id,
            "task_id": task_id_map.get(str(item.get("task_id"))),
            "idempotency_key": item.get("idempotency_key"),
            "observations": [str(value) for value in item.get("observations", [])],
        }
        if status in {"not_started", "in_progress", "unknown"}:
            state["operations"]["open"].append(operation)
        event = _event("v1_operation_migrated", "migration", f"Migrated v1 operation {operation_id}", operation_id)
        event["intended_effect_id"] = effect_id
        event["previous_status"] = item.get("status")
        event["new_status"] = status
        event["references"] = operation["observations"]
        events.append(event)
        if status in {"failed", "unknown"} and effect_id not in successful_effects:
            state["blockers"]["active"].append(
                {
                    "id": f"BLK-{operation_id}",
                    "intended_effect_id": effect_id,
                    "reason": f"Migrated unresolved operation {operation_id}",
                }
            )

    for item in v1.get("sources", []):
        if not isinstance(item, dict):
            continue
        source = copy.deepcopy(item)
        source["id"] = _migrated_id("SRC-", item.get("id"))
        used_by = [
            _migrated_id("REQ-", value)
            for value in item.get("used_by", [])
            if _migrated_id("REQ-", value) in requirement_ids
        ]
        source["used_by"] = used_by
        if used_by:
            state["sources"]["active"].append(source)
        else:
            events.append(
                _event("v1_source_archived", "migration", "Archived source without active dependency", source["id"])
            )

    for item in v1.get("gates", []):
        if not isinstance(item, dict) or item.get("kind") != "approval" or not item.get("required", True):
            continue
        permission = {
            "id": _migrated_id("PERM-", item.get("id")),
            "title": str(item.get("title") or item.get("id")),
            "required": True,
            "status": "granted" if item.get("status") == "passed" else "pending",
            "approval_ref": item.get("approval_ref"),
        }
        state["permissions"]["active"].append(permission)

    for item in v1.get("blockers", []):
        if not isinstance(item, dict):
            continue
        blocker = copy.deepcopy(item)
        blocker["id"] = _migrated_id("BLK-", item.get("id"))
        if not any(existing.get("id") == blocker["id"] for existing in state["blockers"]["active"]):
            state["blockers"]["active"].append(blocker)

    known_top = {
        "schema_version", "skill_version", "revision", "updated_at", "project", "scope",
        "capabilities", "requirements", "tasks", "checks", "operations", "sources", "gates",
        "blockers", "notes", "next_action",
    }
    unknown_top = {key: copy.deepcopy(value) for key, value in v1.items() if key not in known_top}
    notes = v1.get("notes") if isinstance(v1.get("notes"), dict) else {}
    unknown_notes = {
        key: copy.deepcopy(value)
        for key, value in notes.items()
        if key not in {"decisions", "questions", "hazards", "approvals", "incidents", "data_update_history"}
    }
    state["legacy"] = {
        "source_schema_version": 1,
        "source_revision": v1.get("revision"),
        "project_context": {
            key: copy.deepcopy(project.get(key))
            for key in ("profile", "risk", "lifecycle", "version")
        },
        "preferences": {"sales_page": scope.get("sales_page")},
        "unmapped": {**unknown_top, "notes": unknown_notes} if unknown_notes else unknown_top,
    }
    migration_event = _event("state_migrated", "migration", "Migrated state schema 1 to 2", state["project_id"])
    migration_event["previous_status"] = "schema-1"
    migration_event["new_status"] = "schema-2"
    events.append(migration_event)
    return state, events


def migrate_project(root: Path, target_version: str) -> dict[str, Any]:
    root = _root(root)
    harness_dir = _harness_dir(root)
    state_path = harness_dir / "state.json"
    try:
        raw = state_path.read_bytes()
        v1 = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HarnessError(f"cannot read v1 state: {exc}") from exc
    if not isinstance(v1, dict):
        raise HarnessError("v1 state must be an object")
    candidate, events = _convert_v1_state(v1, target_version)
    issues = validate_state(candidate)
    if issues:
        raise ValidationError(issues)

    token = acquire_lock(root, "migration")
    try:
        current_raw = state_path.read_bytes()
        if current_raw != raw:
            raise ConflictError("v1 state changed during migration preparation")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_dir = harness_dir / "migration" / f"{stamp}-{uuid.uuid4().hex[:8]}"
        backup_dir.mkdir(parents=True, exist_ok=False)
        backup_state = backup_dir / "state-v1.json"
        backup_state.write_bytes(raw)
        backup_sha = backup_dir / "state-v1.sha256"
        backup_sha.write_text(hashlib.sha256(raw).hexdigest() + "\n", encoding="utf-8", newline="\n")
        old_events = harness_dir / "events.jsonl"
        if old_events.exists():
            shutil.copy2(old_events, backup_dir / "events-v1.jsonl")
        _write_json_atomic(state_path, candidate)
        event_text = "".join(
            json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
            for event in events
        )
        _write_text_atomic(harness_dir / "events.jsonl", event_text)
        (harness_dir / "evidence").mkdir(exist_ok=True)
        (harness_dir / "proposals").mkdir(exist_ok=True)
        return {
            "status": "ok",
            "backup_state": str(backup_state),
            "backup_sha256": str(backup_sha),
            "active_requirements": len(candidate["requirements"]["active"]),
            "stale_checks": sum(
                item.get("status") == "stale" for item in candidate["checks"]["current"]
            ),
            "open_operations": len(candidate["operations"]["open"]),
            "active_blockers": len(candidate["blockers"]["active"]),
        }
    finally:
        release_lock(root, token)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version="project-harness helper schema 2.0")
    subcommands = parser.add_subparsers(dest="command", required=True)

    init = subcommands.add_parser("init")
    init.add_argument("--root", type=Path, required=True)
    init.add_argument("--name", required=True)
    init.add_argument("--skill-version", required=True)

    for command in ("status", "validate", "lock-status", "recover", "release-check"):
        sub = subcommands.add_parser(command)
        sub.add_argument("--root", type=Path, required=True)

    apply = subcommands.add_parser("apply")
    apply.add_argument("--root", type=Path, required=True)
    apply.add_argument("--candidate", type=Path, required=True)
    apply.add_argument("--expected-revision", type=int, required=True)
    apply.add_argument("--actor", default="primary")

    fingerprint = subcommands.add_parser("fingerprint")
    fingerprint.add_argument("--root", type=Path, required=True)
    fingerprint.add_argument("--path", action="append", required=True)

    for command in ("record-check", "record-operation"):
        record = subcommands.add_parser(command)
        record.add_argument("--root", type=Path, required=True)
        record.add_argument("--record", type=Path, required=True)
        record.add_argument("--expected-revision", type=int, required=True)
        record.add_argument("--actor", default="primary")

    migrate = subcommands.add_parser("migrate")
    migrate.add_argument("--root", type=Path, required=True)
    migrate.add_argument("--target-version", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            path = init_project(args.root, args.name, args.skill_version)
            payload: object = {"status": "ok", "state": str(path)}
        elif args.command == "status":
            payload = status_summary(load_state(args.root))
        elif args.command == "validate":
            issues = validate_state(load_state(args.root))
            if issues:
                print(json.dumps({"status": "invalid", "issues": issues}, ensure_ascii=False), file=sys.stderr)
                return 1
            payload = {"status": "ok"}
        elif args.command == "lock-status":
            lock_path = _harness_dir(args.root) / ".lock"
            payload = {"status": "present" if lock_path.exists() else "absent"}
            if lock_path.exists():
                payload["lock"] = json.loads(lock_path.read_text(encoding="utf-8"))
        elif args.command == "fingerprint":
            manifest = build_snapshot_manifest(args.root, args.path)
            payload = {
                "status": "ok",
                "snapshot_fingerprint": snapshot_fingerprint(args.root, args.path),
                "manifest": manifest,
            }
        elif args.command == "recover":
            payload = recovery_summary(load_state(args.root))
        elif args.command == "release-check":
            issues = release_issues(load_state(args.root), args.root)
            if issues:
                print(json.dumps({"status": "blocked", "issues": issues}, ensure_ascii=False), file=sys.stderr)
                return 1
            payload = {"status": "ok", "release_ready": True}
        elif args.command == "record-check":
            payload = record_check(
                args.root, _load_candidate(args.record), args.expected_revision, args.actor
            )
        elif args.command == "record-operation":
            payload = record_operation(
                args.root, _load_candidate(args.record), args.expected_revision, args.actor
            )
        elif args.command == "migrate":
            payload = migrate_project(args.root, args.target_version)
        else:
            candidate = _load_candidate(args.candidate)
            payload = apply_candidate(args.root, candidate, args.expected_revision, args.actor)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except ValidationError as exc:
        print(json.dumps({"status": "invalid", "issues": exc.issues}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (ConflictError, HarnessError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
