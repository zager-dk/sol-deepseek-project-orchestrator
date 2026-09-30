#!/usr/bin/env python3
"""Install the Sol + DeepSeek orchestrator skill, agent, and hooks.

Cross-platform, standard library only. The installer is deliberately boring:

  * it plans every write before touching disk,
  * it never overwrites a differing file unless you pass --force,
  * it never overwrites PROJECT_STATE.md or AGENTS.md at all,
  * it never edits config.toml, user-level hooks.json, credentials, or routing,
  * it never reaches the network.

Exit codes:
    0  success (including a clean dry run)
    2  usage or environment problem
    3  conflicts detected and nothing was written

Examples:
    python scripts/install.py --project /path/to/repo --codex-home ~/.codex
    python scripts/install.py --project /path/to/repo --codex-home ~/.codex --hooks
    CODEX_HOME=~/.codex python scripts/install.py --project /path/to/repo --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "sol-deepseek-project-orchestrator"
AGENT_FILE_NAME = "deepseek-worker.toml"
INTEGRATOR_FILE_NAME = "deepseek-integrator.toml"

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_CONFLICT = 3

CREATE = "create"
UPDATE = "update"
UNCHANGED = "unchanged"
PRESERVE = "preserve"
CONFLICT = "conflict"
REMOVE = "remove"

MANAGED = "managed"
USER_OWNED = "user-owned"


class InstallError(Exception):
    """A usage or environment problem that must stop the install."""


@dataclass
class PlanItem:
    action: str
    path: Path
    origin: str
    kind: str = MANAGED
    source: Path | None = None
    content: bytes | None = None
    note: str = ""

    def display_path(self) -> str:
        return str(self.path)


@dataclass
class Plan:
    items: list[PlanItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, item: PlanItem) -> None:
        self.items.append(item)

    def conflicts(self) -> list[PlanItem]:
        return [item for item in self.items if item.action == CONFLICT]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def read_source(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise InstallError(f"cannot read bundled file {path}: {exc}") from exc


def read_existing(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None
    except IsADirectoryError:
        return None
    except OSError:
        return None


def classify_managed(dest: Path, content: bytes) -> str:
    existing = read_existing(dest)
    if existing is None:
        return CREATE
    if existing == content:
        return UNCHANGED
    return CONFLICT


def classify_user_owned(dest: Path) -> str:
    return PRESERVE if dest.exists() else CREATE


def add_file_plan(
    plan: Plan,
    source: Path,
    dest: Path,
    origin: str,
    kind: str = MANAGED,
) -> None:
    content = read_source(source)
    action = (
        classify_user_owned(dest)
        if kind == USER_OWNED
        else classify_managed(dest, content)
    )
    note = ""
    if action == PRESERVE:
        note = "existing file kept"
    plan.add(
        PlanItem(
            action=action,
            path=dest,
            origin=origin,
            kind=kind,
            source=source,
            content=content,
            note=note,
        )
    )


def add_generated_plan(
    plan: Plan,
    dest: Path,
    origin: str,
    content: bytes,
    kind: str = MANAGED,
) -> None:
    action = (
        classify_user_owned(dest)
        if kind == USER_OWNED
        else classify_managed(dest, content)
    )
    plan.add(
        PlanItem(
            action=action,
            path=dest,
            origin=origin,
            kind=kind,
            source=None,
            content=content,
        )
    )


# ---------------------------------------------------------------------------
# Hook configuration
# ---------------------------------------------------------------------------


def posix_interpreter() -> str:
    if os.name != "nt":
        found = shutil.which("python3") or shutil.which("python")
        if found:
            return found
    return "python3"


def windows_interpreter() -> str | None:
    if os.name != "nt":
        return None
    if sys.executable:
        return sys.executable
    return shutil.which("python") or shutil.which("py")


def hook_command(script: Path, use_windows: bool) -> str | None:
    if use_windows:
        interpreter = windows_interpreter()
        if not interpreter:
            return None
        return f'"{interpreter}" "{script}"'
    return f'{posix_interpreter()} "{script.as_posix()}"'


def build_hooks_config(hooks_dir: Path) -> bytes:
    inject = hooks_dir / "inject_project_state.py"
    stop = hooks_dir / "stop_project_state_check.py"

    def handler(script: Path, status: str, extra: dict | None = None) -> dict:
        handler_dict: dict = {
            "type": "command",
            "command": hook_command(script, use_windows=False),
        }
        windows = hook_command(script, use_windows=True)
        if windows:
            # In hooks.json the key is camelCase; only TOML accepts
            # command_windows. See the Codex hooks documentation, "Notes".
            handler_dict["commandWindows"] = windows
        handler_dict["timeout"] = 20 if script is stop else 15
        handler_dict["statusMessage"] = status
        if extra:
            handler_dict.update(extra)
        return handler_dict

    config = {
        "_generated": (
            "Generated by sol-deepseek-project-orchestrator scripts/install.py. "
            "Re-run the installer with --hooks --force after moving this "
            "repository, because the commands below contain absolute paths."
        ),
        "description": (
            "Project state injection and one-shot state nudge for the "
            "Sol + DeepSeek thin-root workflow."
        ),
        "hooks": {
            # SessionStart with source "compact" is what covers the window
            # after compaction: Codex runs matching SessionStart hooks before
            # the next model request, including mid-turn automatic compaction.
            # PostCompact only supports the common output fields, so it cannot
            # carry additionalContext.
            "SessionStart": [
                {
                    "matcher": "startup|resume|clear|compact",
                    "hooks": [
                        handler(
                            inject,
                            "Loading project state",
                            {"additionalContextLimit": 4000},
                        )
                    ],
                }
            ],
            "Stop": [
                {
                    "hooks": [handler(stop, "Checking project state")],
                }
            ],
        },
    }
    text = json.dumps(config, indent=2, ensure_ascii=False) + "\n"
    return text.encode("utf-8")


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def iter_source_tree(root: Path) -> list[Path]:
    if not root.is_dir():
        raise InstallError(f"bundled directory missing: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            files.append(path)
    return files


def build_plan(
    project: Path,
    codex_home: Path,
    *,
    with_hooks: bool,
    with_agents_md: bool,
    with_agent: bool,
    prune: bool,
    plan: Plan,
    with_integrator: bool = False,
) -> Plan:
    skill_dir = REPO_ROOT / "skill"
    skill_dest = codex_home / "skills" / SKILL_NAME

    for source in iter_source_tree(skill_dir):
        relative = source.relative_to(skill_dir)
        add_file_plan(
            plan,
            source,
            skill_dest / relative,
            origin="skill",
        )

    architecture = REPO_ROOT / "ARCHITECTURE.md"
    if architecture.is_file():
        add_file_plan(
            plan,
            architecture,
            skill_dest / "ARCHITECTURE.md",
            origin="skill-doc",
        )
    else:
        plan.warnings.append(
            "ARCHITECTURE.md is missing from the bundle; installed skill will "
            "not carry the long-form design document."
        )

    if with_agent:
        add_file_plan(
            plan,
            REPO_ROOT / "templates" / "agents" / AGENT_FILE_NAME,
            codex_home / "agents" / AGENT_FILE_NAME,
            origin="agent",
        )

    if with_integrator:
        add_file_plan(
            plan,
            REPO_ROOT / "templates" / "agents" / INTEGRATOR_FILE_NAME,
            codex_home / "agents" / INTEGRATOR_FILE_NAME,
            origin="integrator",
        )

    add_file_plan(
        plan,
        REPO_ROOT / "templates" / "PROJECT_STATE.md",
        project / ".codex" / "PROJECT_STATE.md",
        origin="state-template",
        kind=USER_OWNED,
    )

    if with_agents_md:
        add_file_plan(
            plan,
            REPO_ROOT / "templates" / "AGENTS.md",
            project / "AGENTS.md",
            origin="agents-template",
            kind=USER_OWNED,
        )

    if with_hooks:
        hooks_dest_dir = project / ".codex" / "hooks"
        for source in iter_source_tree(REPO_ROOT / "hooks"):
            if source.suffix != ".py":
                continue
            add_file_plan(
                plan,
                source,
                hooks_dest_dir / source.name,
                origin="hooks",
            )
        add_generated_plan(
            plan,
            project / ".codex" / "hooks.json",
            origin="hooks-config",
            content=build_hooks_config(hooks_dest_dir),
        )

    if prune and skill_dest.is_dir():
        planned = {item.path.resolve() for item in plan.items}
        for existing in sorted(skill_dest.rglob("*")):
            if not existing.is_file() or "__pycache__" in existing.parts:
                continue
            if existing.resolve() not in planned:
                plan.add(
                    PlanItem(
                        action=REMOVE,
                        path=existing,
                        origin="skill-prune",
                        note="not part of this bundle",
                    )
                )

    return plan


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------


def atomic_write(dest: Path, content: bytes, backup: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if backup and dest.exists():
        shutil.copy2(dest, dest.with_name(dest.name + ".bak"))
    temporary = dest.with_name(dest.name + ".tmp-install")
    temporary.write_bytes(content)
    os.replace(temporary, dest)


def apply_plan(plan: Plan, *, force: bool, dry_run: bool) -> dict:
    written: list[str] = []
    updated: list[str] = []
    removed: list[str] = []
    preserved: list[str] = []
    unchanged: list[str] = []

    for item in plan.items:
        # A conflict is only unresolved without --force; the caller already
        # returned exit code 3 in that case, so here it means "replace".
        if item.action == CONFLICT and force:
            item.action = UPDATE
        if item.action == UNCHANGED:
            unchanged.append(item.display_path())
            continue
        if item.action == PRESERVE:
            preserved.append(item.display_path())
            continue
        if item.action == CONFLICT:
            continue
        if item.action == REMOVE:
            if dry_run:
                removed.append(item.display_path())
                continue
            try:
                item.path.unlink()
                removed.append(item.display_path())
            except OSError as exc:
                plan.warnings.append(f"could not remove {item.path}: {exc}")
            continue

        if item.action == CREATE:
            if dry_run:
                written.append(item.display_path())
                continue
            content = (
                item.content
                if item.content is not None
                else read_source(item.source)  # type: ignore[arg-type]
            )
            atomic_write(item.path, content, backup=False)
            written.append(item.display_path())
        elif item.action == UPDATE:
            if dry_run:
                updated.append(item.display_path())
                continue
            content = (
                item.content
                if item.content is not None
                else read_source(item.source)  # type: ignore[arg-type]
            )
            atomic_write(item.path, content, backup=force)
            updated.append(item.display_path())

    return {
        "created": written,
        "updated": updated,
        "removed": removed,
        "preserved": preserved,
        "unchanged": unchanged,
        "warnings": plan.warnings,
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_plan(plan: Plan, codex_home: Path, project: Path) -> str:
    lines = [
        f"repository  : {REPO_ROOT}",
        f"codex home  : {codex_home}",
        f"project     : {project}",
        "",
        f"{'ACTION':<10} {'ORIGIN':<15} PATH",
    ]
    for item in plan.items:
        suffix = f"  ({item.note})" if item.note else ""
        lines.append(
            f"{item.action:<10} {item.origin:<15} {item.display_path()}{suffix}"
        )
    if plan.warnings:
        lines.append("")
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in plan.warnings)
    return "\n".join(lines)


def remediation_hint(conflicts: list[PlanItem]) -> str:
    lines = [
        "",
        "Nothing was written. These files already exist with different content:",
    ]
    lines.extend(f"- {item.display_path()}" for item in conflicts)
    lines.extend(
        [
            "",
            "Options:",
            "  * re-run with --force to replace the managed files listed above",
            "    (each replaced file is backed up next to the original as .bak)",
            "  * delete the listed files yourself, then re-run without --force",
            "  * point --codex-home or --project somewhere else",
            "",
            "PROJECT_STATE.md and AGENTS.md are user-owned and are never overwritten.",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def resolve_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    project = Path(args.project).expanduser()
    if not project.exists():
        raise InstallError(f"--project does not exist: {project}")
    if not project.is_dir():
        raise InstallError(f"--project is not a directory: {project}")
    project = project.resolve()

    codex_home_raw = args.codex_home or os.environ.get("CODEX_HOME")
    if not codex_home_raw:
        raise InstallError(
            "no Codex home given. Pass --codex-home PATH or set CODEX_HOME. "
            "The installer refuses to guess, because writing into the wrong "
            "directory is not recoverable for the user."
        )
    codex_home = Path(codex_home_raw).expanduser()
    return project, codex_home


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description=(
            "Install the Sol + DeepSeek orchestrator skill, worker agent, "
            "project state template, and optional project hooks."
        ),
    )
    parser.add_argument("--project", required=True, help="target project root")
    parser.add_argument(
        "--codex-home",
        default=None,
        help="Codex home directory (falls back to the CODEX_HOME variable)",
    )
    parser.add_argument(
        "--hooks",
        action="store_true",
        help="also install project-local state hooks and .codex/hooks.json",
    )
    parser.add_argument(
        "--agents-md",
        action="store_true",
        help="also drop the example AGENTS.md into the project root",
    )
    parser.add_argument(
        "--adaptive",
        action="store_true",
        help="also install the DeepSeek integrator for adaptive parallel work",
    )
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="skip all custom agents (manage worker/integrator routing yourself)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace managed files that differ, backing each one up as .bak",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="remove files inside the installed skill directory that are not in this bundle",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and exit without writing anything",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the plan and result as JSON instead of a table",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    try:
        project, codex_home = resolve_paths(args)
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    plan = Plan()
    try:
        build_plan(
            project,
            codex_home,
            with_hooks=args.hooks,
            with_agents_md=args.agents_md,
            with_agent=not args.no_agent,
            prune=args.prune,
            plan=plan,
            with_integrator=args.adaptive and not args.no_agent,
        )
    except InstallError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if not (project / ".git").exists():
        plan.warnings.append(
            "project does not look like a git repository (no .git directory); "
            "the Stop hook needs git to detect repository changes."
        )
    if not (codex_home / "config.toml").exists():
        plan.warnings.append(
            f"no config.toml found in {codex_home}; the installer still writes "
            "there, but double-check that this is your real Codex home."
        )

    conflicts = plan.conflicts()
    blocked = bool(conflicts) and not args.force

    if args.json:
        payload = {
            "status": (
                "conflict" if blocked else ("planned" if args.dry_run else "ok")
            ),
            "repository": str(REPO_ROOT),
            "codex_home": str(codex_home),
            "project": str(project),
            "actions": [
                {
                    "action": item.action,
                    "origin": item.origin,
                    "path": item.display_path(),
                }
                for item in plan.items
            ],
            "conflicts": [item.display_path() for item in conflicts],
            "warnings": plan.warnings,
            "exit_code": EXIT_CONFLICT if blocked else EXIT_OK,
        }
        if not blocked and not args.dry_run:
            payload["result"] = apply_plan(plan, force=args.force, dry_run=False)
        print(json.dumps(payload, indent=2))
        return EXIT_CONFLICT if blocked else EXIT_OK

    print(render_plan(plan, codex_home, project))

    if blocked:
        print(remediation_hint(conflicts))
        return EXIT_CONFLICT

    if args.dry_run:
        print("\nDry run: nothing was written.")
        return EXIT_OK

    result = apply_plan(plan, force=args.force, dry_run=False)
    print("")
    print(f"created   : {len(result['created'])}")
    print(f"updated   : {len(result['updated'])}")
    print(f"removed   : {len(result['removed'])}")
    print(f"preserved : {len(result['preserved'])}")
    print(f"unchanged : {len(result['unchanged'])}")
    for warning in result["warnings"]:
        print(f"warning   : {warning}")

    if args.hooks:
        print("")
        print("Hooks installed at project scope. Review and trust them with /hooks")
        print("before they run, and re-run this installer after moving the repo.")

    print("")
    print("Next: restart or reopen Codex so the skill and agent are picked up,")
    print("then read QUICKSTART.md for the first dispatch.")
    return EXIT_OK


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)
