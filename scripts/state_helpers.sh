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
  curl -sS \
    -H "Authorization: Bearer ${token}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/artifacts/${artifact_id}/zip" \
    -o "${RUNNER_TEMP}/amway-state.zip"

  mkdir -p "${GITHUB_WORKSPACE}/data"

  local extract_dir="${RUNNER_TEMP}/amway-state-extract"
  rm -rf "${extract_dir}"
  mkdir -p "${extract_dir}"
  (cd "${extract_dir}" && unzip -o "${RUNNER_TEMP}/amway-state.zip")

  # upload-artifact may flatten data/*.json to the zip root, or keep a data/ prefix
  if compgen -G "${extract_dir}/data/*.json" > /dev/null 2>&1; then
    cp "${extract_dir}"/data/*.json "${GITHUB_WORKSPACE}/data/"
  else
    cp "${extract_dir}"/*.json "${GITHUB_WORKSPACE}/data/"
  fi

  local count
  count="$(find "${GITHUB_WORKSPACE}/data" -name '*.json' 2>/dev/null | wc -l)"
  echo "[state] Restored ${count} json file(s)."
}