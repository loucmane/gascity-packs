
Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

1. Read current step bead metadata and get `gc.root_bead_id`; hard-fail if it is
   missing. Read that do-work root with `gc bd show <root-bead-id> --json`.
2. Resolve the input convoy from the do-work root:
   - read root metadata `gc.input_convoy_id`; hard-fail if it is missing
   - verify `gc.input_convoy_id` matches rendered runtime convoy `{{convoy_id}}`
   - read that input convoy with `gc bd show <input-convoy-id> --json`
   - set the initial `<source-anchor-id>` to `<input-convoy-id>` and use the exact
     input-convoy record as the initial source anchor. Do not select a tracked
     member yourself. The executable helper is the sole source-anchor resolver:
     it resolves system-created singleton and drain-unit convoys to their tracked
     member and fails closed on missing or ambiguous membership.
3. Serialize a request JSON object containing only these fields: `repository`
   (a checkout of the source repository), `launcher_checkout` (the current
   launcher's top-level checkout), `source_anchor_id`, and the exact JSON records
   already read as `source_anchor`, `input_convoy`, and `do_work_root`. Do not
   add inferred base or path candidates to the request. Write that object to a
   file and set `REQUEST_JSON` to the absolute path of that file; `REQUEST_JSON`
   is a file path, not inline JSON. Read `gc.formula_source` from the do-work
   root metadata, require it to be an absolute path to the cooked
   `do-work.formula.toml`, and set `FORMULA_SOURCE` to that exact value. This
   binds the helper to the same pinned pack revision that supplied the formula;
   do not search `PATH`, pack caches, or the launcher checkout for another copy.
4. Run
   `"$(dirname "$FORMULA_SOURCE")/../assets/scripts/prepare_worktree.py" --request "$REQUEST_JSON"`.
   This helper is the sole authority for base/path resolution, item-branch
   creation, policy checks, and worktree creation or reuse.
   Do not restate, reimplement, or bypass its decisions. A launcher checkout's
   `HEAD` is unrelated runtime state and is
   never a fallback. `WORKTREE_POLICY.md` may expose machine-readable
   `<!-- gc.worktree_root=/absolute/path -->` and
   `<!-- gc.protected_checkout=/absolute/path -->` directives to the helper.
   On success, read `<source-anchor-id>` from `source_anchor_id`, `BASE_COMMIT`
   from `base_commit`, and `WORKTREE` from `worktree_path`. Read `BRANCH` from `branch`
   in its JSON output. The helper
   verifies that the actual worktree `HEAD` equals the explicit base, attaches
   the worktree to the deterministic local `codex/<source-anchor-id>` branch,
   and reports whether a valid pre-provisioned source-anchor `work_dir` was
   reused. Never leave a successful prepared worktree detached.
5. On a nonzero helper exit, persist each emitted metadata entry on the current
   step with `gc bd update <claimed-step-id> --set-metadata <key>=<value>`, then
   fail closed. Contradictory, unresolvable, or missing base input emits
   `gc.conflict_base_commit`; contradictory, unsafe, or missing explicit or
   policy-derived path input emits `gc.conflict_worktree_path`. Never substitute
   launcher `HEAD` or an in-repository default path. An invalid, conflicting,
   or already-occupied item branch emits `gc.conflict_worktree_branch`; never
   invent an alternate branch name.
6. Read the helper-resolved source anchor with
   `gc bd show <source-anchor-id> --json`. Validate context path {{context_path}},
   files ownership, and verification policy for that source anchor. Persist the
   helper decision as root metadata `gc.source_anchor_id` with
   `gc bd update <root-bead-id> --set-metadata gc.source_anchor_id=<source-anchor-id>`.
   Persist the absolute path on the source
   anchor with `gc bd update <source-anchor-id> --set-metadata work_dir=<absolute worktree path>`.
   For synthetic drain-unit convoys, never persist `work_dir` on the synthetic drain-unit convoy; the original drain member/source anchor is authoritative.
   Verify the source anchor now has `work_dir` before closing this step with
   `gc.outcome=pass`.
