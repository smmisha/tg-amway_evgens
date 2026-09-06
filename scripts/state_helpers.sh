#!/usr/bin/env bash
# Persist bot state (data/*.json) via GitHub Actions artifacts so content
# stays out of the public repository while surviving between runs.
set -euo pipefail

ARTIFACT_NAME="amway-state"
ARTIFACTS_API="https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/artifacts?per_page=100"

restore_state() {
  local token="${GITHUB_TOKEN:?GITHUB_TOKEN is not set}"
  local artifact_id

  artifact_id="$(curl -sS \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.github+json" \
    "${ARTIFACTS_API}" \
    | jq -r '[.artifacts[] | select(.name == "'"${ARTIFACT_NAME}"'" and .expired == false)] | sort_by(.created_at) | reverse | .[0].id // empty')"

  if [[ -z "${artifact_id}" ]]; then
    echo "[state] No previous artifact found - starting with an empty dataset."
    mkdir -p "${GITHUB_WORKSPACE}/data"
    return 0
  fi

  echo "[state] Restoring state from artifact #${artifact_id}..."
  curl -sSL \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}/zip" \
    -o "${RUNNER_TEMP}/amway-state.zip"

  mkdir -p "${GITHUB_WORKSPACE}/data"

  local extract_dir="${RUNNER_TEMP}/amway-state-extract"
  rm -rf "${extract_dir}"
  mkdir -p "${extract_dir}"
  (cd "${extract_dir}" && unzip -o "${RUNNER_TEMP}/amway-state.zip")

  # Restore ONLY mutable runtime state files.
  # NEVER overwrite git-tracked static data (products_catalog.json, books_bundle.json).
  local state_files=("published.json" "attempted.json" "prepared_posts.json" "last_update_id.txt")
  local restored=0

  for sf in "${state_files[@]}"; do
    if [[ -f "${extract_dir}/data/${sf}" ]]; then
      cp -f "${extract_dir}/data/${sf}" "${GITHUB_WORKSPACE}/data/${sf}"
      restored=$((restored + 1))
    elif [[ -f "${extract_dir}/${sf}" ]]; then
      cp -f "${extract_dir}/${sf}" "${GITHUB_WORKSPACE}/data/${sf}"
      restored=$((restored + 1))
    fi
  done

  echo "[state] Restored ${restored} runtime state file(s). Protected git-tracked catalog and books."
}