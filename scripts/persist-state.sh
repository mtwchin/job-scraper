#!/usr/bin/env bash
# Commit and push seen_jobs.json back to the repo.
#
# This file is the only record of what has already been sent to Discord, so a
# failed push is not a cosmetic problem: the next run would start from stale
# state and re-send every job it already delivered. Hence the retries, and the
# union-merge against the remote copy instead of a plain rebase — rebasing two
# commits that both rewrite the same JSON file just conflicts.
#
# Usage:
#   persist-state.sh once             commit+push if there is anything to push
#   persist-state.sh loop <seconds>   do that every <seconds> until killed
set -uo pipefail

# Exported, not just set: `jobscraper merge-state` resolves its state file from
# the environment and otherwise falls back to a path relative to the installed
# package, which is not necessarily the checkout we are persisting.
STATE_FILE="${STATE_FILE:-seen_jobs.json}"
export STATE_FILE
BRANCH="${PERSIST_BRANCH:-main}"
MAX_ATTEMPTS="${PERSIST_MAX_ATTEMPTS:-5}"

# Not every environment has a bare `python` on PATH. Resolve it once rather than
# letting the merge step fail quietly — a skipped merge silently discards the
# remote's records, which is exactly the re-notification bug this guards against.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if command -v python3 >/dev/null 2>&1; then PYTHON=python3
  elif command -v python >/dev/null 2>&1; then PYTHON=python
  else echo "[persist] ERROR: no python interpreter on PATH" >&2; exit 1
  fi
fi

log() { echo "[persist] $*"; }

# `git show <rev>:<path>` needs a path relative to the repo root, but STATE_FILE
# may legitimately be absolute (the workflow exports one).
git_relative_state() {
  local root
  root="$(git rev-parse --show-toplevel)"
  "$PYTHON" -c "import os,sys;print(os.path.relpath(os.path.abspath(sys.argv[1]), sys.argv[2]))" \
    "$STATE_FILE" "$root"
}

record_count() {
  "$PYTHON" -c "import json,sys;print(json.load(open(sys.argv[1]))['count'])" "$STATE_FILE" 2>/dev/null \
    || echo '?'
}

push_once() {
  [ -f "$STATE_FILE" ] || { log "no $STATE_FILE yet"; return 0; }

  # Nothing to do if our copy already matches what is committed.
  if git diff --quiet -- "$STATE_FILE" && git diff --cached --quiet -- "$STATE_FILE"; then
    return 0
  fi

  local attempt=1 delay=2
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    if ! git fetch --quiet origin "$BRANCH"; then
      log "fetch failed (attempt $attempt/$MAX_ATTEMPTS)"
      sleep "$delay"; attempt=$((attempt + 1)); delay=$((delay * 2)); continue
    fi

    # Fold in anything the remote knows that we do not, so a record written by
    # another run is never dropped — dropping it would re-notify that job.
    local remote_copy merge_ok=1
    remote_copy="$(mktemp)"
    if git show "origin/$BRANCH:$(git_relative_state)" > "$remote_copy" 2>/dev/null; then
      "$PYTHON" -m jobscraper merge-state "$remote_copy" || merge_ok=0
    fi
    rm -f "$remote_copy"
    if [ "$merge_ok" -eq 0 ]; then
      # Pushing now would overwrite the remote with a state file that is missing
      # whatever the remote had — every one of those jobs would then look new and
      # be re-sent. Back off and retry instead.
      log "merge failed (attempt $attempt/$MAX_ATTEMPTS); not pushing a partial state"
      sleep "$delay"; attempt=$((attempt + 1)); delay=$((delay * 2)); continue
    fi

    # Re-anchor onto the remote tip carrying our merged state across, rather
    # than rebasing one JSON rewrite onto another.
    local merged
    merged="$(mktemp)"
    cp "$STATE_FILE" "$merged"
    git checkout --quiet --force -B "$BRANCH" "origin/$BRANCH"
    cp "$merged" "$STATE_FILE"
    rm -f "$merged"

    git add "$STATE_FILE"
    if git diff --cached --quiet; then
      log "state already matches origin/$BRANCH"
      return 0
    fi

    git commit --quiet -m "chore: update seen jobs [skip ci]"
    if git push --quiet origin "HEAD:$BRANCH"; then
      log "pushed $(record_count) records"
      return 0
    fi

    log "push rejected (attempt $attempt/$MAX_ATTEMPTS); re-merging and retrying in ${delay}s"
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done

  log "ERROR: could not push state after $MAX_ATTEMPTS attempts"
  return 1
}

case "${1:-once}" in
  once)
    push_once
    ;;
  loop)
    # Periodic checkpoint while a watch loop runs, so a runner that dies part
    # way through still has most of its "already sent" record committed.
    interval="${2:-300}"
    log "checkpointing every ${interval}s"
    while true; do
      sleep "$interval"
      push_once || true
    done
    ;;
  *)
    echo "usage: $0 {once|loop <seconds>}" >&2
    exit 2
    ;;
esac
