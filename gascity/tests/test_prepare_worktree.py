from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest


PACK_ROOT = pathlib.Path(__file__).resolve().parents[1]
PREPARE_WORKTREE = PACK_ROOT / "assets" / "scripts" / "prepare_worktree.py"


class PrepareWorktreeBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.temp = pathlib.Path(self._temp_dir.name).resolve()
        self.launcher = self.temp / "launcher"
        self.launcher.mkdir()
        self._git("init", cwd=self.launcher)
        self._git("config", "user.name", "Fixture User", cwd=self.launcher)
        self._git("config", "user.email", "fixture@example.invalid", cwd=self.launcher)
        self._git("config", "commit.gpgsign", "false", cwd=self.launcher)

        target = self.launcher / "target-subtree" / "implementation.txt"
        target.parent.mkdir()
        target.write_text("target branch only\n", encoding="utf-8")
        self._git("add", ".", cwd=self.launcher)
        self._git("commit", "-m", "target base", cwd=self.launcher)
        self.base_commit = self._git("rev-parse", "HEAD", cwd=self.launcher).stdout.strip()

        self._git("checkout", "--orphan", "launcher-unrelated", cwd=self.launcher)
        target.unlink()
        target.parent.rmdir()
        self._git("add", "-A", cwd=self.launcher)
        self._git("commit", "--allow-empty", "-m", "unrelated launcher", cwd=self.launcher)
        self.launcher_commit = self._git("rev-parse", "HEAD", cwd=self.launcher).stdout.strip()

        self.assertNotEqual(self.launcher_commit, self.base_commit)
        self.assertFalse((self.launcher / "target-subtree").exists())

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def _git(self, *args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
            text=True,
            capture_output=True,
            check=True,
        )

    def _request(
        self,
        *,
        source_anchor_id: str = "anchor-123",
        source_anchor: dict[str, object] | None = None,
        input_convoy: dict[str, object] | None = None,
        do_work_root: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "repository": str(self.launcher),
            "launcher_checkout": str(self.launcher),
            "source_anchor_id": source_anchor_id,
            "source_anchor": source_anchor or {"metadata": {}},
            "input_convoy": input_convoy or {"metadata": {}},
            "do_work_root": do_work_root or {"metadata": {}},
        }

    def _run_helper(self, request: dict[str, object]) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
        request_path = self.temp / "request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(PREPARE_WORKTREE), "--request", str(request_path)],
            cwd=self.launcher,
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {}
        return result, payload

    def _assert_conflict(self, request: dict[str, object], key: str) -> dict[str, object]:
        result, payload = self._run_helper(request)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(payload.get("ok"), payload)
        metadata = payload.get("metadata")
        self.assertIsInstance(metadata, dict, payload)
        self.assertIn(key, metadata, payload)
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.launcher).stdout.strip(), self.launcher_commit)
        return payload

    def _branch(self, worktree: pathlib.Path) -> str:
        return self._git("symbolic-ref", "--short", "HEAD", cwd=worktree).stdout.strip()

    def test_explicit_base_and_path_create_external_worktree_from_base(self) -> None:
        worktree = self.temp / "worktrees" / "explicit-anchor"
        result, payload = self._run_helper(
            self._request(
                source_anchor={
                    "metadata": {
                        "gc.base_commit": self.base_commit,
                        "gc.worktree_path": str(worktree),
                    }
                }
            )
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("base_commit"), self.base_commit)
        self.assertEqual(pathlib.Path(str(payload.get("worktree_path"))).resolve(), worktree.resolve())
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=worktree).stdout.strip(), self.base_commit)
        self.assertEqual(payload.get("branch"), "codex/anchor-123")
        self.assertEqual(self._branch(worktree), "codex/anchor-123")
        self.assertTrue((worktree / "target-subtree" / "implementation.txt").is_file())
        self.assertNotEqual(self._git("rev-parse", "HEAD", cwd=worktree).stdout.strip(), self.launcher_commit)
        self.assertNotEqual(worktree, self.launcher)
        self.assertNotIn(self.launcher, worktree.parents)

    def test_policy_root_creates_external_worktree_from_explicit_base(self) -> None:
        rig_root = self.temp / "rig"
        policy_root = self.temp / "policy-worktrees"
        rig_root.mkdir()
        (rig_root / "WORKTREE_POLICY.md").write_text(
            "# Worktree policy\n\n"
            f"<!-- gc.worktree_root={policy_root} -->\n"
            f"<!-- gc.protected_checkout={self.launcher} -->\n",
            encoding="utf-8",
        )
        expected = policy_root / "anchor-123"
        result, payload = self._run_helper(
            self._request(
                input_convoy={"target": self.base_commit, "metadata": {}},
                do_work_root={"metadata": {"gc.work_dir": str(rig_root)}},
            )
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(pathlib.Path(str(payload.get("worktree_path"))).resolve(), expected.resolve())
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=expected).stdout.strip(), self.base_commit)
        self.assertEqual(payload.get("branch"), "codex/anchor-123")
        self.assertEqual(self._branch(expected), "codex/anchor-123")
        self.assertNotIn(self.launcher, expected.parents)

    def test_reuses_preprovisioned_source_anchor_work_dir(self) -> None:
        worktree = self.temp / "preprovisioned" / "anchor-123"
        self._git("worktree", "add", "--detach", str(worktree), self.base_commit, cwd=self.launcher)
        marker = worktree / "round-6-marker"
        marker.write_text("keep me\n", encoding="utf-8")
        before = worktree.stat()

        result, payload = self._run_helper(
            self._request(
                source_anchor={
                    "metadata": {
                        "gc.base_commit": self.base_commit,
                        "work_dir": str(worktree),
                    }
                }
            )
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload.get("ok"), payload)
        self.assertTrue(payload.get("reused"), payload)
        self.assertEqual(worktree.stat().st_ino, before.st_ino)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=worktree).stdout.strip(), self.base_commit)
        self.assertEqual(payload.get("branch"), "codex/anchor-123")
        self.assertEqual(self._branch(worktree), "codex/anchor-123")

        second_result, second_payload = self._run_helper(
            self._request(
                source_anchor={
                    "metadata": {
                        "gc.base_commit": self.base_commit,
                        "work_dir": str(worktree),
                    }
                }
            )
        )
        self.assertEqual(second_result.returncode, 0, second_result.stdout + second_result.stderr)
        self.assertTrue(second_payload.get("reused"), second_payload)
        self.assertEqual(second_payload.get("branch"), "codex/anchor-123")
        self.assertEqual(self._branch(worktree), "codex/anchor-123")
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep me\n")

    def test_synthetic_singleton_convoy_resolves_tracked_source_anchor(self) -> None:
        worktree = self.temp / "worktrees" / "gct-3lje"
        member = {
            "id": "gct-3lje",
            "metadata": {
                "gc.base_commit": self.base_commit,
                "gc.worktree_path": str(worktree),
            },
            "dependency_type": "tracks",
        }
        input_convoy = {
            "id": "gct-6qcl",
            "metadata": {"gc.synthetic": "true"},
            "dependencies": [member],
        }

        result, payload = self._run_helper(
            self._request(
                source_anchor_id="gct-6qcl",
                source_anchor=input_convoy,
                input_convoy=input_convoy,
            )
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(payload.get("ok"), payload)
        self.assertEqual(payload.get("source_anchor_id"), "gct-3lje")
        self.assertEqual(payload.get("base_commit"), self.base_commit)
        self.assertEqual(pathlib.Path(str(payload.get("worktree_path"))).resolve(), worktree.resolve())
        self.assertEqual(payload.get("branch"), "codex/gct-3lje")
        self.assertEqual(self._branch(worktree), "codex/gct-3lje")

    def test_synthetic_input_convoy_with_multiple_tracked_members_fails_closed(self) -> None:
        first = {
            "id": "gct-first",
            "metadata": {"gc.base_commit": self.base_commit},
            "dependency_type": "tracks",
        }
        second = {
            "id": "gct-second",
            "metadata": {"gc.base_commit": self.base_commit},
            "dependency_type": "tracks",
        }
        input_convoy = {
            "id": "gct-many",
            "metadata": {"gc.synthetic": "true"},
            "dependencies": [first, second],
        }

        payload = self._assert_conflict(
            self._request(
                source_anchor_id="gct-many",
                source_anchor=input_convoy,
                input_convoy=input_convoy,
            ),
            "gc.conflict_worktree_path",
        )

        self.assertIn("exactly one tracked member", str(payload["metadata"]["gc.conflict_worktree_path"]))

    def test_existing_item_branch_at_another_commit_fails_closed(self) -> None:
        branch = "codex/anchor-123"
        worktree = self.temp / "worktrees" / "branch-conflict"
        self._git("branch", branch, self.launcher_commit, cwd=self.launcher)

        payload = self._assert_conflict(
            self._request(
                source_anchor={
                    "metadata": {
                        "gc.base_commit": self.base_commit,
                        "gc.worktree_path": str(worktree),
                    }
                }
            ),
            "gc.conflict_worktree_branch",
        )

        self.assertIn(branch, str(payload["metadata"]["gc.conflict_worktree_branch"]))
        self.assertFalse(worktree.exists())

    def test_contradictory_base_candidates_emit_conflict_and_fail_closed(self) -> None:
        worktree = self.temp / "worktrees" / "base-conflict"
        request = self._request(
            source_anchor={
                "metadata": {
                    "gc.base_commit": self.base_commit,
                    "gc.worktree_path": str(worktree),
                }
            },
            input_convoy={"target": self.launcher_commit, "metadata": {}},
        )

        self._assert_conflict(request, "gc.conflict_base_commit")
        self.assertFalse(worktree.exists())

    def test_contradictory_path_candidates_emit_conflict_and_fail_closed(self) -> None:
        first = self.temp / "worktrees-a" / "anchor-123"
        second = self.temp / "worktrees-b" / "anchor-123"
        request = self._request(
            source_anchor={
                "metadata": {
                    "gc.base_commit": self.base_commit,
                    "gc.worktree_path": str(first),
                }
            },
            input_convoy={"metadata": {"gc.worktree_path": str(second)}},
        )

        self._assert_conflict(request, "gc.conflict_worktree_path")
        self.assertFalse(first.exists())
        self.assertFalse(second.exists())

    def test_missing_base_emits_conflict_without_using_launcher_head(self) -> None:
        worktree = self.temp / "worktrees" / "missing-base"
        request = self._request(source_anchor={"metadata": {"gc.worktree_path": str(worktree)}})

        payload = self._assert_conflict(request, "gc.conflict_base_commit")
        self.assertNotEqual(payload.get("base_commit"), self.launcher_commit)
        self.assertFalse(worktree.exists())

    def test_missing_path_emits_conflict_without_in_repo_default(self) -> None:
        request = self._request(source_anchor={"metadata": {"gc.base_commit": self.base_commit}})

        self._assert_conflict(request, "gc.conflict_worktree_path")
        self.assertFalse((self.launcher / "worktrees" / "anchor-123").exists())


if __name__ == "__main__":
    unittest.main()
