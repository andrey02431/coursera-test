#!/usr/bin/env bash
# Example wrapper for cron. Assumes a venv at <repo>/.venv.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

source .venv/bin/activate
python -m blackboard_sync sync
