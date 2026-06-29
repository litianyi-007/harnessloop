#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
python "$REPO_ROOT/plugins/harnessloop/skills/harnessloop-loop/scripts/init_project.py" "$@"

