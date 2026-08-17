
Resolve and publish the isolated worktree for this item. This is infrastructure
setup only. Do not edit source files in the launcher checkout.

1. Read current step bead metadata and get `gc.root_bead_id`; hard-fail if it is
   missing. Read that do-work root with `bd show <root-bead-id> --json`.
2. Resolve `<source-anchor-id>` from the do-work root:
   - read root metadata `gc.input_convoy_id`; hard-fail if it is missing
   - verify `gc.input_convoy_id` matches rendered runtime convoy `{{convoy_id}}`
   - read that input convoy with `bd show <input-convoy-id> --json`
   - if input convoy metadata has `gc.synthetic_kind=drain-unit-convoy`, use
     input convoy metadata `gc.drain_member_id`
   - do not use the synthetic drain-unit convoy id as `<source-anchor-id>`;
     hard-fail if the selected source anchor id equals the synthetic input convoy id
   - otherwise use `<input-convoy-id>` as the source anchor
   - if root metadata also has `gc.drain_member_id`, it must match the selected
     drain member
3. Read the selected source anchor with `bd show <source-anchor-id> --json`.
   Resolve an explicit base from the source anchor's or input convoy's metadata
   keys `gc.base_commit` and `gc.base_ref`, plus the input convoy's top-level `target`.
   Resolve every supplied candidate to a commit in this repository.
   All supplied candidates must resolve to the same commit, stored as
   `BASE_COMMIT`. A launcher checkout's `HEAD` is unrelated runtime state:
   never use it as a base candidate or fallback. If no explicit base candidate is present,
   a candidate cannot resolve, or explicit base candidates resolve to different commits,
   record `gc.conflict_base_commit` and fail closed.
4. Resolve `WORKTREE` without using the current directory as a default. Accept
   the source anchor's existing `work_dir`, an absolute `gc.worktree_path`, or
   a path formed by appending `<source-anchor-id>` to an absolute
   `gc.worktree_root`; these explicit metadata keys may be on the source anchor,
   input convoy, or do-work root. Also read the launcher rig root from the
   do-work root's `gc.work_dir` and obey its `WORKTREE_POLICY.md`, including any
   policy-derived worktree root. Canonicalize every resulting candidate and
   require it to select the same location. The selected path must satisfy the
   rig policy and be outside the launcher checkout and every other protected
   checkout. If no explicit or policy-derived worktree location is present,
   worktree path candidates contradict each other, or the selected path violates
   policy, record `gc.conflict_worktree_path` and fail closed. A valid
   pre-provisioned source-anchor `work_dir` must be reused, not replaced.
5. Validate context path {{context_path}}, files ownership, and verification
   policy for the resolved source anchor. If `WORKTREE` is missing, create it at
   the resolved external path with
   `git worktree add "$WORKTREE" --detach "$BASE_COMMIT"`. If it exists, verify
   it is this repository's worktree. In both cases, verify
   `git -C "$WORKTREE" rev-parse HEAD` equals `BASE_COMMIT`; never substitute
   launcher state for either value.
6. Persist the absolute path on the source anchor with
   `bd update <source-anchor-id> --set-metadata work_dir=<absolute worktree path>`.
   For synthetic drain-unit convoys, never persist `work_dir` on the synthetic drain-unit convoy; the original drain member/source anchor is authoritative.
   Verify the source anchor now has `work_dir` before closing this step with
   `gc.outcome=pass`.
