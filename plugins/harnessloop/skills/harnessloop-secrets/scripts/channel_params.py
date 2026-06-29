#!/usr/bin/env python3
"""Manage Harnessloop local channel parameter metadata and values."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


STORE_REL = Path(".harnessloop/local/channel-params.json")
GITIGNORE_REL = Path(".harnessloop/local/.gitignore")
EXAMPLE_REL = Path(".harnessloop/local/channel-params.example.json")

DEFAULT_IGNORE_LINES = [
    "channel-params.json",
    "*.secret.json",
    "*.token",
    "*.key",
    "*.pem",
    "secrets/",
]

SENSITIVITY_VALUES = [
    "public",
    "internal",
    "credential-reference",
    "secret",
    "unknown",
]

STORAGE_VALUES = [
    "local-file",
    "env",
    "os-keychain",
    "vault",
    "onepassword",
    "manual",
    "unknown",
]


def base_store() -> dict[str, Any]:
    return {"version": 1, "channels": {}}


def store_path(project: Path) -> Path:
    return project / STORE_REL


def gitignore_path(project: Path) -> Path:
    return project / GITIGNORE_REL


def example_path(project: Path) -> Path:
    return project / EXAMPLE_REL


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return base_store()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SystemExit(f"Invalid store shape in {path}: root must be an object")
    value.setdefault("version", 1)
    value.setdefault("channels", {})
    if not isinstance(value["channels"], dict):
        raise SystemExit(f"Invalid store shape in {path}: channels must be an object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ensure_local_files(project: Path) -> list[str]:
    changed: list[str] = []
    local_dir = project / ".harnessloop/local"
    local_dir.mkdir(parents=True, exist_ok=True)

    ignore = gitignore_path(project)
    if ignore.exists():
        existing = ignore.read_text(encoding="utf-8").splitlines()
    else:
        existing = []
    additions = [line for line in DEFAULT_IGNORE_LINES if line not in existing]
    if additions:
        new_lines = existing + additions
        ignore.write_text("\n".join(new_lines).strip() + "\n", encoding="utf-8")
        changed.append(str(ignore))

    example = example_path(project)
    if not example.exists():
        example_value = {
            "version": 1,
            "channels": {
                "example-channel": {
                    "parameters": {
                        "EXAMPLE_TOKEN": {
                            "sensitivity": "secret",
                            "storage": "env",
                            "env": "EXAMPLE_TOKEN",
                            "value": None,
                            "required_for": ["connectivity"],
                            "status": "missing",
                            "notes": "Replace with project-specific keys. Never commit real values.",
                        }
                    }
                }
            },
        }
        write_json(example, example_value)
        changed.append(str(example))

    return changed


def get_channel(store: dict[str, Any], channel_id: str) -> dict[str, Any]:
    channels = store.setdefault("channels", {})
    channel = channels.setdefault(channel_id, {})
    channel.setdefault("parameters", {})
    return channel


def parameter_status(key: str, param: dict[str, Any]) -> tuple[str, str]:
    storage = param.get("storage", "unknown")
    if storage == "local-file":
        return ("present", "local-file") if param.get("value") else ("missing", "local-file")
    if storage == "env":
        env_name = param.get("env") or key
        return ("present", f"env:{env_name}") if os.environ.get(env_name) else ("missing", f"env:{env_name}")
    if storage in {"vault", "onepassword", "os-keychain"}:
        reference = param.get("reference") or param.get("reference_name")
        return ("unknown", f"{storage}:{reference}") if reference else ("missing", storage)
    if storage == "manual":
        return ("unknown", "manual")
    return ("unknown", "unknown")


def redacted_parameter(key: str, param: dict[str, Any]) -> dict[str, Any]:
    status, source = parameter_status(key, param)
    result = {
        "name": key,
        "sensitivity": param.get("sensitivity", "unknown"),
        "storage": param.get("storage", "unknown"),
        "source": source,
        "required_for": param.get("required_for", []),
        "status": status,
        "notes": param.get("notes", ""),
    }
    if param.get("env"):
        result["env"] = param["env"]
    if param.get("reference"):
        result["reference"] = param["reference"]
    return result


def missing_fields(key: str, param: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if param.get("sensitivity", "unknown") == "unknown":
        missing.append(f"{key}.sensitivity")
    storage = param.get("storage", "unknown")
    if storage == "unknown":
        missing.append(f"{key}.storage")
    elif storage == "env" and not param.get("env"):
        missing.append(f"{key}.env")
    elif storage in {"vault", "onepassword", "os-keychain"} and not param.get("reference"):
        missing.append(f"{key}.reference")
    if not param.get("required_for"):
        missing.append(f"{key}.required_for")
    return missing


def emit(result: dict[str, Any]) -> int:
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return int(result.get("exit_code", 0))


def cmd_init(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    changed = ensure_local_files(project)
    store = read_json(store_path(project))
    if not store_path(project).exists():
        write_json(store_path(project), store)
        changed.append(str(store_path(project)))
    return emit(
        {
            "project": str(project),
            "action": "init",
            "local_store": str(store_path(project)),
            "files_changed": changed,
            "status": "ready",
        }
    )


def cmd_add(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    changed = ensure_local_files(project)
    store = read_json(store_path(project))
    channel = get_channel(store, args.channel)
    parameters = channel["parameters"]
    existing = parameters.get(args.key, {})
    required_for = sorted(set(existing.get("required_for", []) + (args.required_for or [])))
    param = {
        "sensitivity": args.sensitivity,
        "storage": args.storage,
        "env": args.env if args.env else (args.key if args.storage == "env" else existing.get("env")),
        "reference": args.reference if args.reference else existing.get("reference"),
        "value": existing.get("value"),
        "required_for": required_for,
        "status": existing.get("status", "unknown"),
        "notes": args.notes if args.notes is not None else existing.get("notes", ""),
    }
    status, _source = parameter_status(args.key, param)
    param["status"] = status
    parameters[args.key] = {k: v for k, v in param.items() if v is not None}
    write_json(store_path(project), store)
    changed.append(str(store_path(project)))
    redacted = redacted_parameter(args.key, parameters[args.key])
    missing = missing_fields(args.key, parameters[args.key])
    blocked = bool(missing) or redacted["status"] in {"missing", "unknown", "invalid"}
    questions = questions_for_missing(args.channel, missing) + questions_for_unresolved(args.channel, [redacted])
    return emit(
        {
            "project": str(project),
            "action": "add",
            "channel": args.channel,
            "local_store": str(store_path(project)),
            "keys": [redacted],
            "files_changed": changed,
            "missing_fields": missing,
            "questions_for_user": questions,
            "next_action": "set missing values or run connectivity after required parameters are present",
            "exit_code": 2 if blocked else 0,
        }
    )


def read_secret_value(args: argparse.Namespace) -> str:
    sources = [bool(args.value_env), bool(args.value_file), bool(args.value_stdin)]
    if sum(sources) != 1:
        raise SystemExit("Use exactly one of --value-env, --value-file, or --value-stdin")
    if args.value_env:
        value = os.environ.get(args.value_env)
        if value is None:
            raise SystemExit(f"Environment variable is not set: {args.value_env}")
        return value
    if args.value_file:
        return Path(args.value_file).read_text(encoding="utf-8").rstrip("\r\n")
    return sys.stdin.read().rstrip("\r\n")


def cmd_set(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    changed = ensure_local_files(project)
    store = read_json(store_path(project))
    channel = get_channel(store, args.channel)
    parameters = channel["parameters"]
    if args.key not in parameters and not args.create:
        raise SystemExit(f"Missing parameter key: {args.channel}.{args.key}. Use add first or pass --create.")
    existing = parameters.get(args.key, {})
    value = read_secret_value(args)
    required_for = sorted(set(existing.get("required_for", []) + (args.required_for or [])))
    param = {
        "sensitivity": args.sensitivity or existing.get("sensitivity", "secret"),
        "storage": "local-file",
        "env": None,
        "reference": None,
        "value": value,
        "required_for": required_for,
        "status": "present" if value else "missing",
        "notes": args.notes if args.notes is not None else existing.get("notes", ""),
    }
    parameters[args.key] = {k: v for k, v in param.items() if v is not None}
    write_json(store_path(project), store)
    changed.append(str(store_path(project)))
    return emit(
        {
            "project": str(project),
            "action": "set",
            "channel": args.channel,
            "local_store": str(store_path(project)),
            "keys": [redacted_parameter(args.key, parameters[args.key])],
            "files_changed": changed,
            "next_action": "run check or connectivity; secret value was not printed",
        }
    )


def collect_parameters(store: dict[str, Any], channel_filter: str | None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for channel_id, channel in sorted(store.get("channels", {}).items()):
        if channel_filter and channel_id != channel_filter:
            continue
        parameters = channel.get("parameters", {})
        for key, param in sorted(parameters.items()):
            item = redacted_parameter(key, param)
            item["channel"] = channel_id
            item["missing_fields"] = missing_fields(key, param)
            collected.append(item)
    return collected


def questions_for_missing(channel_id: str, missing: list[str]) -> list[str]:
    questions: list[str] = []
    for field in missing:
        questions.append(f"Provide {field} for channel {channel_id}, or confirm it should remain unresolved.")
    return questions


def questions_for_unresolved(channel_id: str, items: list[dict[str, Any]]) -> list[str]:
    questions: list[str] = []
    for item in items:
        if item["status"] == "present":
            continue
        name = item["name"]
        storage = item["storage"]
        source = item["source"]
        if storage == "env":
            env_name = source.removeprefix("env:")
            questions.append(
                f"Set environment variable {env_name} for channel {channel_id}, "
                f"or confirm a different storage method for {name}."
            )
        elif storage == "local-file":
            questions.append(
                f"Provide {name} for channel {channel_id} through the ignored local store, "
                "or confirm it should remain missing."
            )
        elif storage in {"vault", "onepassword", "os-keychain"}:
            questions.append(
                f"Confirm the {storage} reference for {name} on channel {channel_id} is accessible, "
                "or provide the correct reference name."
            )
        else:
            questions.append(
                f"Confirm storage and value source for {name} on channel {channel_id} before access is attempted."
            )
    return questions


def cmd_check(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    store = read_json(store_path(project))
    if args.channel and args.channel not in store.get("channels", {}):
        return emit(
            {
                "project": str(project),
                "action": "check",
                "channel": args.channel,
                "local_store": str(store_path(project)),
                "keys": [],
                "missing_fields": [f"{args.channel}.declaration"],
                "questions_for_user": [
                    f"Declare channel {args.channel} and its required parameters before connectivity or evidence collection."
                ],
                "overall_status": "blocked",
                "exit_code": 2,
            }
        )
    keys = collect_parameters(store, args.channel)
    if args.channel and not keys:
        return emit(
            {
                "project": str(project),
                "action": "check",
                "channel": args.channel,
                "local_store": str(store_path(project)),
                "keys": [],
                "missing_fields": [f"{args.channel}.parameters"],
                "questions_for_user": [
                    f"Declare the required parameter keys for channel {args.channel} before access is attempted."
                ],
                "overall_status": "blocked",
                "exit_code": 2,
            }
        )
    missing = [field for item in keys for field in item["missing_fields"]]
    unresolved = [item for item in keys if item["status"] in {"missing", "unknown", "invalid"}]
    questions = questions_for_missing(args.channel or "all", missing)
    questions += questions_for_unresolved(args.channel or "all", unresolved)
    return emit(
        {
            "project": str(project),
            "action": "check",
            "channel": args.channel or "all",
            "local_store": str(store_path(project)),
            "keys": keys,
            "missing_fields": missing,
            "questions_for_user": questions,
            "overall_status": "pass" if not unresolved and not missing else "blocked",
            "exit_code": 2 if unresolved or missing else 0,
        }
    )


def cmd_resolve(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    store = read_json(store_path(project))
    channel = store.get("channels", {}).get(args.channel, {})
    parameters = channel.get("parameters", {})
    if args.key not in parameters:
        return emit(
            {
                "project": str(project),
                "action": "resolve",
                "channel": args.channel,
                "key": args.key,
                "status": "missing",
                "missing_fields": [f"{args.key}.declaration"],
                "questions_for_user": [
                    f"Declare parameter {args.key} for channel {args.channel} before using it."
                ],
                "exit_code": 2,
            }
        )
    item = redacted_parameter(args.key, parameters[args.key])
    missing = missing_fields(args.key, parameters[args.key])
    questions = questions_for_missing(args.channel, missing)
    questions += questions_for_unresolved(args.channel, [item])
    return emit(
        {
            "project": str(project),
            "action": "resolve",
            "channel": args.channel,
            "local_store": str(store_path(project)),
            "keys": [item],
            "missing_fields": missing,
            "questions_for_user": questions,
            "exit_code": 2 if item["status"] in {"missing", "unknown", "invalid"} or missing else 0,
        }
    )


def cmd_audit(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    store = read_json(store_path(project))
    ignore = gitignore_path(project)
    ignored = False
    if ignore.exists():
        ignored = "channel-params.json" in ignore.read_text(encoding="utf-8").splitlines()
    keys = collect_parameters(store, None)
    local_value_count = 0
    for channel in store.get("channels", {}).values():
        for param in channel.get("parameters", {}).values():
            if param.get("storage") == "local-file" and param.get("value"):
                local_value_count += 1
    findings = []
    if not ignored:
        findings.append(".harnessloop/local/.gitignore does not ignore channel-params.json")
    return emit(
        {
            "project": str(project),
            "action": "audit",
            "local_store": str(store_path(project)),
            "gitignore_protects_store": ignored,
            "channel_count": len(store.get("channels", {})),
            "parameter_count": len(keys),
            "local_value_count": local_value_count,
            "findings": findings,
            "keys": keys,
            "exit_code": 2 if findings else 0,
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage Harnessloop local channel parameters.")
    parser.add_argument("--project", "-p", default=".", help="Target project directory.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create the local store and protective files.")
    init.set_defaults(func=cmd_init)

    add = subparsers.add_parser("add", help="Create or update a channel parameter key.")
    add.add_argument("--channel", required=True)
    add.add_argument("--key", required=True)
    add.add_argument("--sensitivity", choices=SENSITIVITY_VALUES, default="unknown")
    add.add_argument("--storage", choices=STORAGE_VALUES, default="unknown")
    add.add_argument("--env")
    add.add_argument("--reference")
    add.add_argument("--required-for", action="append", default=[])
    add.add_argument("--notes")
    add.set_defaults(func=cmd_add)

    set_value = subparsers.add_parser("set", help="Set a local-file value without printing it.")
    set_value.add_argument("--channel", required=True)
    set_value.add_argument("--key", required=True)
    set_value.add_argument("--create", action="store_true")
    set_value.add_argument("--sensitivity", choices=SENSITIVITY_VALUES)
    set_value.add_argument("--required-for", action="append", default=[])
    set_value.add_argument("--notes")
    set_value.add_argument("--value-env")
    set_value.add_argument("--value-file")
    set_value.add_argument("--value-stdin", action="store_true")
    set_value.set_defaults(func=cmd_set)

    check = subparsers.add_parser("check", help="Check redacted parameter presence.")
    check.add_argument("--channel")
    check.set_defaults(func=cmd_check)

    resolve = subparsers.add_parser("resolve", help="Resolve one key to redacted status and source.")
    resolve.add_argument("--channel", required=True)
    resolve.add_argument("--key", required=True)
    resolve.set_defaults(func=cmd_resolve)

    audit = subparsers.add_parser("audit", help="Audit local store protection and redacted key state.")
    audit.set_defaults(func=cmd_audit)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
