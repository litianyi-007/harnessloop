#!/usr/bin/env python3
"""Initialize a project-local .harnessloop protocol directory."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REFERENCES_DIR = SKILL_DIR / "references"

BASE_DIRS = [
    ".harnessloop/setup",
    ".harnessloop/local",
    ".harnessloop/intake",
    ".harnessloop/state",
    ".harnessloop/meta/evolution-issues",
    ".harnessloop/evals",
    ".harnessloop/goals",
]

BASE_FILES = {
    ".harnessloop/setup/data-sources.md": "data-sources-template.md",
    ".harnessloop/setup/cost-context-policy.md": "cost-context-policy-template.md",
    ".harnessloop/state/current.md": "current-state-template.md",
    ".harnessloop/state/environment.md": "environment-self-check-template.md",
    ".harnessloop/state/control-contract.md": "control-contract-template.md",
    ".harnessloop/state/evidence-index.md": "evidence-index-template.md",
    ".harnessloop/state/self-check.md": "self-check-template.md",
    ".harnessloop/meta/self-audit.md": "self-audit-template.md",
    ".harnessloop/evals/matrix.md": "eval-matrix-template.md",
}

LOCAL_FILES = {
    ".harnessloop/local/.gitignore": "local-gitignore-template.txt",
    ".harnessloop/local/channel-params.example.json": "channel-params-example-template.json",
}

INTAKE_FILES = {
    ".harnessloop/intake/.gitignore": "intake-gitignore-template.txt",
}


def read_template(name: str) -> str:
    path = REFERENCES_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"Missing template: {path}")
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```(?:markdown)?\s*(.*?)\s*```", text, flags=re.DOTALL)
    if match:
        return match.group(1).strip() + "\n"
    return text.strip() + "\n"


def normalize_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-").lower()
    if not slug:
        raise ValueError("Intake slug cannot be empty")
    if re.match(r"^\d{8}-\d{4}-", slug):
        return slug
    return f"{datetime.now().strftime('%Y%m%d-%H%M')}-{slug}"


def write_file(path: Path, content: str, force: bool, dry_run: bool, result: dict) -> None:
    if path.exists() and not force:
        result["skipped"].append(str(path))
        return
    if dry_run:
        result["would_write"].append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    result["written"].append(str(path))


def ensure_dir(path: Path, dry_run: bool, result: dict) -> None:
    if path.exists():
        result["existing_dirs"].append(str(path))
        return
    if dry_run:
        result["would_create_dirs"].append(str(path))
        return
    path.mkdir(parents=True, exist_ok=True)
    result["created_dirs"].append(str(path))


def initialize(project: Path, intake: str | None, force: bool, dry_run: bool) -> dict:
    project = project.resolve()
    result = {
        "project": str(project),
        "created_dirs": [],
        "existing_dirs": [],
        "would_create_dirs": [],
        "written": [],
        "skipped": [],
        "would_write": [],
        "intake_path": None,
    }

    for rel in BASE_DIRS:
        ensure_dir(project / rel, dry_run, result)

    for rel, template in BASE_FILES.items():
        write_file(project / rel, read_template(template), force, dry_run, result)

    for rel, template in LOCAL_FILES.items():
        write_file(project / rel, read_template(template), force, dry_run, result)

    for rel, template in INTAKE_FILES.items():
        write_file(project / rel, read_template(template), force, dry_run, result)

    if intake:
        intake_dir = project / ".harnessloop/intake" / normalize_slug(intake)
        result["intake_path"] = str(intake_dir)
        ensure_dir(intake_dir, dry_run, result)
        write_file(
            intake_dir / "transfer-packet.md",
            read_template("transfer-packet-template.md"),
            force,
            dry_run,
            result,
        )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize .harnessloop in a target project.")
    parser.add_argument("--project", "-p", default=".", help="Target project directory. Defaults to current directory.")
    parser.add_argument("--intake", help="Create an intake transfer-packet directory for an existing-session takeover.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing generated files.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    result = initialize(Path(args.project), args.intake, args.force, args.dry_run)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Harnessloop project: {result['project']}")
        for key in ("created_dirs", "written", "skipped", "would_create_dirs", "would_write"):
            values = result[key]
            if values:
                print(f"{key}:")
                for value in values:
                    print(f"  - {value}")
        if result["intake_path"]:
            print(f"intake_path: {result['intake_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
