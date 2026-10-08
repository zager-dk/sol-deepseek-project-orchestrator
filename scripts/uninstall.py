#!/usr/bin/env python3
"""Safely remove unchanged installer-managed files and release shared claims."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Optional

from install import (
    LOCK_NAME, MANIFEST_NAME, REGISTRY_NAME, InstallError, drop_registry_owner,
    installation_lock, is_shared_path, read_registry, read_valid_manifest,
    validate_destination, validated_managed_records, write_json_atomic,
    write_manifest,
)

EXIT_OK = 0
EXIT_ERROR = 2


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="uninstall.py", description="Remove unchanged installer-managed files.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--codex-home", default=None)
    parser.add_argument("--purge-state", action="store_true", help="also delete .codex/PROJECT_STATE.md")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _uninstall_locked(args: argparse.Namespace, project: Path, codex_home: Path) -> int:
    manifest_path = project / ".codex" / MANIFEST_NAME
    results: dict[str, str] = {}
    roots = (project.resolve(), codex_home.resolve())
    validate_destination(manifest_path, roots)
    if manifest_path.is_symlink():
        raise InstallError("install manifest is a symlink; refusing to follow it")

    manifest = read_valid_manifest(manifest_path)
    if manifest is None and manifest_path.exists():
        raise InstallError("install manifest is invalid or has an altered checksum")
    if manifest is None:
        manifest = {"version": 1, "files": {}}
        results["manifest"] = "absent; no project-local ownership claims were found"
        manual_hooks = project / ".codex" / "hooks.json"
        if manual_hooks.is_file():
            results[str(manual_hooks)] = "kept: no installer manifest proves ownership"

    managed, rejected = validated_managed_records(manifest, project, codex_home)
    for raw_path, reason in rejected.items():
        results[raw_path] = f"kept: {reason}"

    registry = read_registry(codex_home)
    registry_path = codex_home / REGISTRY_NAME
    # A registry claim can recover a manifest update interrupted after the
    # shared file operation. Both paths remain constrained by the exact allowlist.
    for raw_path, record in registry["files"].items():
        if str(project) in record["owners"]:
            managed.setdefault(raw_path, record["sha256"])

    remaining = dict(managed)
    for raw_path, expected in managed.items():
        candidate = Path(raw_path)
        shared = is_shared_path(candidate, codex_home)
        registry_record = registry["files"].get(raw_path)
        other_owners = [
            owner for owner in (registry_record or {}).get("owners", [])
            if owner != str(project)
        ]
        try:
            validate_destination(candidate, roots)
        except InstallError:
            results[raw_path] = "kept: path changed to a reparse point during uninstall"
            continue

        if shared and registry_record is None:
            # Legacy installs have no cross-project ownership evidence. Keep
            # shared bytes until a re-install registers current participants.
            results[raw_path] = "kept: shared ownership is unknown; re-install to register it before removal"
            continue

        if shared and other_owners:
            # This project is finished; release its reference while retaining
            # the shared bytes for every remaining registered project.
            results[raw_path] = "kept: shared with " + ", ".join(other_owners)
            remaining.pop(raw_path, None)
            drop_registry_owner(registry, raw_path, project)
            if not args.dry_run:
                write_json_atomic(registry_path, registry, roots)
                write_manifest(project, codex_home, remaining)
            continue

        try:
            data = candidate.read_bytes()
        except FileNotFoundError:
            results[raw_path] = "absent"
            remaining.pop(raw_path, None)
            if shared:
                drop_registry_owner(registry, raw_path, project)
                if not args.dry_run:
                    write_json_atomic(registry_path, registry, roots)
            if not args.dry_run:
                write_manifest(project, codex_home, remaining)
            continue
        except OSError as exc:
            results[raw_path] = f"failed: {exc}"
            continue
        if not isinstance(expected, str) or hashlib.sha256(data).hexdigest() != expected:
            results[raw_path] = "kept: modified since installation"
            # Changed bytes are now user data. Release a shared claim so no
            # other project's uninstall can treat them as installer-owned.
            if shared:
                remaining.pop(raw_path, None)
                drop_registry_owner(registry, raw_path, project)
                if not args.dry_run:
                    write_json_atomic(registry_path, registry, roots)
                    write_manifest(project, codex_home, remaining)
            continue
        if args.dry_run:
            results[raw_path] = "would-remove"
            continue
        try:
            validate_destination(candidate, roots)
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
                results[raw_path] = "kept: modified during uninstall"
                continue
            candidate.unlink()
            results[raw_path] = "removed"
            remaining.pop(raw_path, None)
            if shared:
                drop_registry_owner(registry, raw_path, project)
                write_json_atomic(registry_path, registry, roots)
            write_manifest(project, codex_home, remaining)
        except InstallError as exc:
            results[raw_path] = f"kept: {exc}"
        except OSError as exc:
            # Keep manifest and registry claims so a later uninstall can retry.
            results[raw_path] = f"failed: {exc}"

    if not args.dry_run:
        # Remove only empty parents below the explicit roots.
        for raw_path in managed:
            parent = Path(raw_path).parent
            for root in roots:
                absolute = Path(os.path.abspath(parent))
                if absolute == root or root not in absolute.parents:
                    continue
                current = absolute
                while current != root and root in current.parents:
                    try:
                        validate_destination(current, roots)
                        current.rmdir()
                    except (OSError, InstallError):
                        break
                    current = current.parent
                break

    state = project / ".codex" / "PROJECT_STATE.md"
    validate_destination(state, roots)
    if args.purge_state and state.is_file():
        if args.dry_run:
            results[str(state)] = "would-remove (explicit --purge-state)"
        else:
            try:
                validate_destination(state, roots)
                state.unlink()
                results[str(state)] = "removed (explicit --purge-state)"
            except (InstallError, OSError) as exc:
                results[str(state)] = f"failed: {exc}"
    elif state.exists():
        results[str(state)] = "kept: user-owned project state"

    failures = any(value.startswith("failed:") for value in results.values())
    # Preserve a manifest for modified files and failed unlinks. If its own
    # unlink fails, it remains intact and the next run can retry.
    if manifest_path.exists() and not args.dry_run:
        if remaining:
            write_manifest(project, codex_home, remaining)
            results[str(manifest_path)] = "kept: tracks modified files or failed removals"
        else:
            try:
                validate_destination(manifest_path, roots)
                manifest_path.unlink()
                results[str(manifest_path)] = "removed"
            except OSError as exc:
                results[str(manifest_path)] = f"failed: {exc}"
                failures = True

    if not args.dry_run and not registry["files"] and registry_path.exists():
        try:
            validate_destination(registry_path, roots)
            registry_path.unlink()
        except OSError as exc:
            results[str(registry_path)] = f"failed: {exc}"
            failures = True

    if args.json:
        print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    else:
        for path, value in results.items():
            print(f"{value:<36} {path}")
        if args.dry_run:
            print("\nDry run: nothing was removed.")
    return EXIT_ERROR if failures else EXIT_OK


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    project_raw = Path(args.project).expanduser()
    if not project_raw.is_dir():
        print(f"error: --project is not a directory: {project_raw}", file=sys.stderr)
        return EXIT_ERROR
    project = project_raw.resolve()
    raw_home = args.codex_home or os.environ.get("CODEX_HOME")
    if not raw_home:
        print("error: no Codex home given. Pass --codex-home PATH or set CODEX_HOME.", file=sys.stderr)
        return EXIT_ERROR
    codex_home = Path(raw_home).expanduser().resolve()
    try:
        with installation_lock(codex_home):
            return _uninstall_locked(args, project, codex_home)
    except (InstallError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
