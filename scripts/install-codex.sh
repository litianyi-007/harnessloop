#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
skip_marketplace_add="false"

for arg in "$@"; do
  case "$arg" in
    --skip-marketplace-add)
      skip_marketplace_add="true"
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ "$skip_marketplace_add" != "true" ]]; then
  codex plugin marketplace add "$repo_root"
fi

codex plugin add "harnessloop@harnessloop"
