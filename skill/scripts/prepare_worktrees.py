#!/usr/bin/env python3
"""Prepare 1-3 isolated local writers and, for parallel work, an integrator.

No inference, network, commits, merges, cleanup, or permission changes. Requires
a clean committed project root. Existing worktrees and branches are never reused.
On a partial Git failure, retain the manifest and worktrees for inspection.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


class WorkspaceError(Exception):
    pass


def git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(project), *args], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if result.returncode:
        raise WorkspaceError(result.stderr.strip() or "Git command failed")
    return result.stdout.strip()


def overlaps(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def plan_worktrees(project: Path, workspace_root: Path, task: str, workers: int) -> dict:
    if not 1 <= workers <= 3:
        raise WorkspaceError("worker count must be 1, 2, or 3")
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,47}", task):
        raise WorkspaceError("task must be 1-48 lowercase letters/digits/hyphens, starting with a letter")
    project = project.resolve()
    workspace_root = workspace_root.resolve()
    if not project.is_dir():
        raise WorkspaceError("project directory does not exist")
    top = Path(git(project, "rev-parse", "--show-toplevel")).resolve()
    if top != project:
        raise WorkspaceError("--project must name the repository root")
    if git(project, "status", "--porcelain", "--untracked-files=all"):
        raise WorkspaceError("project must be clean; no automatic stash or copy of uncommitted files")
    if (project / ".gitmodules").exists():
        raise WorkspaceError("submodule projects require a project-specific isolation procedure")
    baseline = git(project, "rev-parse", "--verify", "HEAD^{commit}")
    common = Path(git(project, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = project / common
    task_root = workspace_root / task
    if overlaps(task_root, project) or overlaps(task_root, common.resolve()):
        raise WorkspaceError("task directory must be outside the project and Git metadata")
    if task_root.exists() or task_root.is_symlink():
        raise WorkspaceError("task directory already exists; choose a fresh task id")
    roles = [f"worker-{i}" for i in range(1, workers + 1)]
    if workers > 1:
        roles.append("integrator")
    entries = []
    for role in roles:
        branch = f"sdo/{task}/{role}"
        result = subprocess.run(
            ["git", "-C", str(project), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0:
            raise WorkspaceError(f"branch already exists: {branch}")
        if result.returncode != 1:
            raise WorkspaceError("cannot check existing branches")
        entries.append({"role": role, "path": str(task_root / role), "branch": branch, "created": False})
    return {
        "schema_version": 1, "task": task, "project": str(project),
        "baseline": baseline, "state_owner": "root", "workers": workers,
        "manifest": str(task_root / "manifest.json"), "workspaces": entries,
    }


def prepare(plan: dict) -> dict:
    project = Path(plan["project"])
    if git(project, "rev-parse", "--verify", "HEAD^{commit}") != plan["baseline"] or git(project, "status", "--porcelain", "--untracked-files=all"):
        raise WorkspaceError("project changed since preflight; prepare a fresh plan")
    manifest = Path(plan["manifest"])
    manifest.parent.mkdir(parents=True, exist_ok=False)

    def save() -> None:
        manifest.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        for entry in plan["workspaces"]:
            git(Path(plan["project"]), "worktree", "add", "-b", entry["branch"], entry["path"], plan["baseline"])
            entry["created"] = True
            save()
    except (WorkspaceError, OSError, subprocess.TimeoutExpired) as exc:
        plan["error"] = str(exc)
        save()
        raise WorkspaceError(f"partial setup preserved; inspect {manifest}: {exc}") from exc
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--workspace-root", required=True, type=Path, help="allowed writable directory outside the project")
    parser.add_argument("--task", required=True)
    parser.add_argument("--workers", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = plan_worktrees(args.project, args.workspace_root, args.task, args.workers)
        if not args.dry_run:
            prepare(plan)
        print(json.dumps(plan, indent=2))
        return 0
    except (WorkspaceError, OSError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
