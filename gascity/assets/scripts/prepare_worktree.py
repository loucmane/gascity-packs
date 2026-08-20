#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BASE_CONFLICT = "gc.conflict_base_commit"
WORKTREE_CONFLICT = "gc.conflict_worktree_path"
BRANCH_CONFLICT = "gc.conflict_worktree_branch"
POLICY_DIRECTIVE = re.compile(
    r"(?:<!--\s*)?(gc\.(?:worktree_root|protected_checkout))\s*[:=]\s*(.*?)\s*(?:-->)?\s*$"
)


@dataclass
class ContractConflict(Exception):
    key: str
    reason: str

    def __str__(self) -> str:
        return self.reason


def run_git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.strip()


def optional_git(repository: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"git exited {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.strip()


def item_branch(repository: Path, source_anchor_id: str) -> str:
    branch = f"codex/{source_anchor_id}"
    try:
        run_git(repository, "check-ref-format", "--branch", branch)
    except RuntimeError as exc:
        raise ContractConflict(BRANCH_CONFLICT, f"derived item branch is invalid: {branch!r}: {exc}") from exc
    return branch


def local_branch_commit(repository: Path, branch: str) -> str | None:
    try:
        return optional_git(
            repository,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{branch}^{{commit}}",
        )
    except RuntimeError as exc:
        raise ContractConflict(BRANCH_CONFLICT, f"cannot inspect item branch {branch!r}: {exc}") from exc


def attach_item_branch(worktree: Path, branch: str, base_commit: str) -> None:
    try:
        current = optional_git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
        if current is None:
            branch_commit = local_branch_commit(worktree, branch)
            if branch_commit is None:
                run_git(worktree, "switch", "-c", branch, base_commit)
            elif branch_commit == base_commit:
                run_git(worktree, "switch", branch)
            else:
                raise ContractConflict(
                    BRANCH_CONFLICT,
                    f"item branch {branch!r} points at {branch_commit}, expected {base_commit}",
                )
        elif current != branch:
            raise ContractConflict(
                BRANCH_CONFLICT,
                f"existing worktree is on branch {current!r}, expected {branch!r}",
            )
        current = optional_git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
    except ContractConflict:
        raise
    except RuntimeError as exc:
        raise ContractConflict(BRANCH_CONFLICT, f"cannot attach item branch {branch!r}: {exc}") from exc
    if current != branch:
        raise ContractConflict(BRANCH_CONFLICT, f"worktree did not attach item branch {branch!r}")


def canonical_path(raw: object, *, label: str, conflict_key: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ContractConflict(conflict_key, f"{label} must be a non-empty absolute path")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ContractConflict(conflict_key, f"{label} must be absolute: {raw!r}")
    return path.resolve(strict=False)


def unwrap_record(value: object, *, label: str) -> dict[str, Any]:
    if isinstance(value, list) and len(value) == 1:
        value = value[0]
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object or one-element object list")
    return value


def metadata(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("metadata", {})
    return value if isinstance(value, dict) else {}


def record_value(record: dict[str, Any], key: str) -> object | None:
    values = metadata(record)
    if key in values:
        return values[key]
    return record.get(key)


def supplied(record: dict[str, Any], key: str) -> list[object]:
    values: list[object] = []
    meta = metadata(record)
    if key in meta:
        values.append(meta[key])
    if key in record and record[key] != meta.get(key):
        values.append(record[key])
    return values


def resolve_base(
    repository: Path,
    source_anchor: dict[str, Any],
    input_convoy: dict[str, Any],
) -> str:
    candidates: list[tuple[str, object]] = []
    for label, record in (("source_anchor", source_anchor), ("input_convoy", input_convoy)):
        for key in ("gc.base_commit", "gc.base_ref"):
            candidates.extend((f"{label}.{key}", value) for value in supplied(record, key))
    if "target" in input_convoy:
        candidates.append(("input_convoy.target", input_convoy["target"]))

    if not candidates:
        raise ContractConflict(BASE_CONFLICT, "no explicit base candidate was supplied")

    resolved: list[tuple[str, str, str]] = []
    for label, raw in candidates:
        if not isinstance(raw, str) or not raw.strip():
            raise ContractConflict(BASE_CONFLICT, f"{label} is not a non-empty revision")
        try:
            commit = run_git(repository, "rev-parse", "--verify", f"{raw.strip()}^{{commit}}")
        except RuntimeError as exc:
            raise ContractConflict(BASE_CONFLICT, f"cannot resolve {label}={raw!r}: {exc}") from exc
        resolved.append((label, raw, commit))

    commits = {commit for _, _, commit in resolved}
    if len(commits) != 1:
        detail = ", ".join(f"{label}={raw!r}->{commit}" for label, raw, commit in resolved)
        raise ContractConflict(BASE_CONFLICT, f"explicit base candidates resolve to different commits: {detail}")
    return commits.pop()


def read_policy(rig_root: Path) -> tuple[list[Path], list[Path]]:
    policy = rig_root / "WORKTREE_POLICY.md"
    if not policy.is_file():
        return [], []

    roots: list[Path] = []
    protected: list[Path] = []
    try:
        lines = policy.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ContractConflict(WORKTREE_CONFLICT, f"cannot read {policy}: {exc}") from exc

    for line in lines:
        match = POLICY_DIRECTIVE.search(line.strip())
        if not match:
            continue
        key, raw = match.groups()
        path = canonical_path(raw, label=f"{policy}:{key}", conflict_key=WORKTREE_CONFLICT)
        if key == "gc.worktree_root":
            roots.append(path)
        else:
            protected.append(path)
    return roots, protected


def resolve_worktree(
    source_anchor_id: str,
    source_anchor: dict[str, Any],
    input_convoy: dict[str, Any],
    do_work_root: dict[str, Any],
) -> tuple[Path, list[Path], list[Path]]:
    if not source_anchor_id or Path(source_anchor_id).name != source_anchor_id or source_anchor_id in {".", ".."}:
        raise ContractConflict(WORKTREE_CONFLICT, "source_anchor_id must be a single safe path component")

    raw_candidates: list[tuple[str, object]] = []
    for value in supplied(source_anchor, "work_dir"):
        raw_candidates.append(("source_anchor.work_dir", value))
    records = (
        ("source_anchor", source_anchor),
        ("input_convoy", input_convoy),
        ("do_work_root", do_work_root),
    )
    for label, record in records:
        for value in supplied(record, "gc.worktree_path"):
            raw_candidates.append((f"{label}.gc.worktree_path", value))
        for value in supplied(record, "gc.worktree_root"):
            root = canonical_path(value, label=f"{label}.gc.worktree_root", conflict_key=WORKTREE_CONFLICT)
            raw_candidates.append((f"{label}.gc.worktree_root/{source_anchor_id}", str(root / source_anchor_id)))

    policy_roots: list[Path] = []
    protected: list[Path] = []
    rig_root_raw = record_value(do_work_root, "gc.work_dir")
    if rig_root_raw is not None:
        rig_root = canonical_path(rig_root_raw, label="do_work_root.gc.work_dir", conflict_key=WORKTREE_CONFLICT)
        policy_roots, protected = read_policy(rig_root)
        for root in policy_roots:
            raw_candidates.append((f"{rig_root}/WORKTREE_POLICY.md:gc.worktree_root/{source_anchor_id}", str(root / source_anchor_id)))

    if not raw_candidates:
        raise ContractConflict(WORKTREE_CONFLICT, "no explicit or policy-derived worktree location was supplied")

    candidates = [
        (label, canonical_path(raw, label=label, conflict_key=WORKTREE_CONFLICT))
        for label, raw in raw_candidates
    ]
    locations = {path for _, path in candidates}
    if len(locations) != 1:
        detail = ", ".join(f"{label}={path}" for label, path in candidates)
        raise ContractConflict(WORKTREE_CONFLICT, f"worktree path candidates contradict each other: {detail}")

    selected = locations.pop()
    for root in policy_roots:
        if selected != root and root not in selected.parents:
            raise ContractConflict(WORKTREE_CONFLICT, f"selected worktree {selected} is outside policy root {root}")
    return selected, policy_roots, protected


def git_worktrees(repository: Path) -> set[Path]:
    try:
        listing = run_git(repository, "worktree", "list", "--porcelain")
    except RuntimeError as exc:
        raise ContractConflict(WORKTREE_CONFLICT, f"cannot list repository worktrees: {exc}") from exc
    return {
        Path(line.removeprefix("worktree ")).resolve(strict=False)
        for line in listing.splitlines()
        if line.startswith("worktree ")
    }


def paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def common_git_dir(repository: Path) -> Path:
    raw = run_git(repository, "rev-parse", "--git-common-dir")
    path = Path(raw)
    if not path.is_absolute():
        path = repository / path
    return path.resolve(strict=False)


def prepare(request: dict[str, Any]) -> dict[str, Any]:
    repository = canonical_path(request.get("repository"), label="repository", conflict_key=BASE_CONFLICT)
    launcher = canonical_path(
        request.get("launcher_checkout"),
        label="launcher_checkout",
        conflict_key=WORKTREE_CONFLICT,
    )
    source_anchor_id = request.get("source_anchor_id")
    if not isinstance(source_anchor_id, str):
        raise ContractConflict(WORKTREE_CONFLICT, "source_anchor_id must be a string")
    source_anchor = unwrap_record(request.get("source_anchor"), label="source_anchor")
    input_convoy = unwrap_record(request.get("input_convoy"), label="input_convoy")
    do_work_root = unwrap_record(request.get("do_work_root"), label="do_work_root")

    try:
        repository_root = canonical_path(
            run_git(repository, "rev-parse", "--show-toplevel"),
            label="repository root",
            conflict_key=BASE_CONFLICT,
        )
        launcher_root = canonical_path(
            run_git(launcher, "rev-parse", "--show-toplevel"),
            label="launcher root",
            conflict_key=WORKTREE_CONFLICT,
        )
        if common_git_dir(repository_root) != common_git_dir(launcher_root):
            raise ContractConflict(WORKTREE_CONFLICT, "launcher checkout does not belong to the requested repository")
    except RuntimeError as exc:
        raise ContractConflict(BASE_CONFLICT, f"repository is not a usable git checkout: {exc}") from exc

    base_commit = resolve_base(repository_root, source_anchor, input_convoy)
    branch = item_branch(repository_root, source_anchor_id)
    branch_commit = local_branch_commit(repository_root, branch)
    if branch_commit is not None and branch_commit != base_commit:
        raise ContractConflict(
            BRANCH_CONFLICT,
            f"item branch {branch!r} points at {branch_commit}, expected explicit base {base_commit}",
        )
    worktree, _, policy_protected = resolve_worktree(
        source_anchor_id,
        source_anchor,
        input_convoy,
        do_work_root,
    )

    if paths_overlap(worktree, launcher_root):
        raise ContractConflict(WORKTREE_CONFLICT, f"worktree {worktree} overlaps launcher checkout {launcher_root}")

    registered = git_worktrees(repository_root)
    for protected in policy_protected:
        if paths_overlap(worktree, protected):
            raise ContractConflict(WORKTREE_CONFLICT, f"worktree {worktree} overlaps protected checkout {protected}")
    for checkout in registered:
        if checkout != worktree and paths_overlap(worktree, checkout):
            raise ContractConflict(WORKTREE_CONFLICT, f"worktree {worktree} overlaps repository checkout {checkout}")

    if worktree.exists():
        if worktree not in registered:
            raise ContractConflict(WORKTREE_CONFLICT, f"existing path is not this repository's registered worktree: {worktree}")
        try:
            if common_git_dir(worktree) != common_git_dir(repository_root):
                raise ContractConflict(WORKTREE_CONFLICT, f"existing worktree belongs to another repository: {worktree}")
            actual_head = run_git(worktree, "rev-parse", "HEAD")
        except RuntimeError as exc:
            raise ContractConflict(WORKTREE_CONFLICT, f"cannot validate existing worktree {worktree}: {exc}") from exc
        if actual_head != base_commit:
            raise ContractConflict(
                BASE_CONFLICT,
                f"existing worktree HEAD {actual_head} does not equal explicit base {base_commit}",
            )
        attach_item_branch(worktree, branch, base_commit)
        reused = True
    else:
        if worktree in registered:
            raise ContractConflict(WORKTREE_CONFLICT, f"registered worktree path is missing: {worktree}")
        worktree.parent.mkdir(parents=True, exist_ok=True)
        try:
            if branch_commit is None:
                run_git(repository_root, "worktree", "add", "-b", branch, str(worktree), base_commit)
            else:
                run_git(repository_root, "worktree", "add", str(worktree), branch)
            actual_head = run_git(worktree, "rev-parse", "HEAD")
        except (OSError, RuntimeError) as exc:
            raise ContractConflict(WORKTREE_CONFLICT, f"cannot create worktree {worktree}: {exc}") from exc
        if actual_head != base_commit:
            raise ContractConflict(
                BASE_CONFLICT,
                f"created worktree HEAD {actual_head} does not equal explicit base {base_commit}",
            )
        attach_item_branch(worktree, branch, base_commit)
        reused = False

    return {
        "ok": True,
        "base_commit": base_commit,
        "branch": branch,
        "worktree_path": str(worktree),
        "reused": reused,
        "metadata": {},
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve and prepare a do-work implementation worktree")
    parser.add_argument("--request", required=True, help="path to the prepare-worktree request JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        request = json.loads(Path(args.request).read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise ValueError("request JSON must be an object")
        payload = prepare(request)
        status = 0
    except ContractConflict as exc:
        payload = {"ok": False, "metadata": {exc.key: exc.reason}}
        status = 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        payload = {"ok": False, "error": str(exc), "metadata": {}}
        status = 1

    json.dump(payload, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
