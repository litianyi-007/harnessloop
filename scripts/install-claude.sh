#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scope="user"
skip_marketplace_add="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)
      scope="${2:-}"
      if [[ -z "$scope" ]]; then
        echo "--scope requires user, project, or local" >&2
        exit 2
      fi
      shift 2
      ;;
    --skip-marketplace-add)
      skip_marketplace_add="true"
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

case "$scope" in
  user|project|local) ;;
  *)
    echo "--scope must be user, project, or local" >&2
    exit 2
    ;;
esac

if [[ "$skip_marketplace_add" != "true" ]]; then
  claude plugin marketplace add "$repo_root" --scope "$scope"
fi

claude plugin install "harnessloop@harnessloop" --scope "$scope"
