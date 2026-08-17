from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import tomllib
import unittest


PACK_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = PACK_ROOT.parent
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


def run_git(repository: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def render_declared_vars(text: str, formula: dict, supplied: dict[str, str]) -> str:
    """Mirror Gas City: render known runtime/default vars and preserve unknowns."""

    values = {
        name: str(spec["default"])
        for name, spec in formula.get("vars", {}).items()
        if "default" in spec
    }
    values.update(supplied)
    return PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), text)


class PrepareWorktreeMaterializationTests(unittest.TestCase):
    def test_pinned_do_work_command_runs_from_clean_launcher(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            revision = run_git(REPO_ROOT, "rev-parse", "HEAD")
            pinned_pack = root / "pack-cache" / revision / "gascity"
            for relative in (
                "pack.toml",
                "formulas/do-work.formula.toml",
                "assets/workflows/do-work/prepare-worktree.md",
                "assets/scripts/prepare_worktree.py",
            ):
                source = PACK_ROOT / relative
                target = pinned_pack / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)

            launcher = root / "launcher"
            launcher.mkdir()
            run_git(launcher, "init", "--quiet")
            run_git(launcher, "config", "user.name", "Materialization Test")
            run_git(launcher, "config", "user.email", "materialization@example.invalid")
            (launcher / "README.md").write_text("clean launcher\n", encoding="utf-8")
            run_git(launcher, "add", "README.md")
            run_git(launcher, "commit", "--quiet", "-m", "fixture")
            base_commit = run_git(launcher, "rev-parse", "HEAD")

            (launcher / "packs.lock").write_text(
                "\n".join(
                    (
                        "schema = 1",
                        "",
                        '[packs."https://example.invalid/gascity-packs/gascity"]',
                        'version = "test"',
                        f'commit = "{revision}"',
                        "",
                    )
                ),
                encoding="utf-8",
            )
            run_git(launcher, "add", "packs.lock")
            run_git(launcher, "commit", "--quiet", "-m", "pin gascity pack")
            self.assertEqual(run_git(launcher, "status", "--porcelain"), "")

            formula_path = pinned_pack / "formulas" / "do-work.formula.toml"
            formula = tomllib.loads(formula_path.read_text(encoding="utf-8"))
            prepare = next(step for step in formula["steps"] if step["id"] == "prepare-worktree")
            description_path = (formula_path.parent / prepare["description_file"]).resolve()
            rendered = render_declared_vars(
                description_path.read_text(encoding="utf-8"),
                formula,
                {"convoy_id": "convoy-fixture"},
            )

            command_match = re.search(r"`([^`\n]*prepare_worktree\.py[^`\n]*)`", rendered)
            self.assertIsNotNone(command_match, "materialized prompt did not emit the helper command")
            command = command_match.group(1)
            self.assertNotIn("{{", command, f"unresolved formula placeholder in emitted command: {command}")

            helper = pinned_pack / "assets" / "scripts" / "prepare_worktree.py"
            self.assertTrue(helper.is_file())
            self.assertTrue(os.access(helper, os.X_OK))
            self.assertIn('$(dirname "$FORMULA_SOURCE")/../assets/scripts/prepare_worktree.py', command)

            request_path = root / "request.json"
            worktree = root / "worktrees" / "source-item"
            request_path.write_text(
                json.dumps(
                    {
                        "repository": str(launcher),
                        "launcher_checkout": str(launcher),
                        "source_anchor_id": "source-item",
                        "source_anchor": {"metadata": {"work_dir": str(worktree)}},
                        "input_convoy": {"target": base_commit},
                        "do_work_root": {
                            "metadata": {
                                "gc.formula_source": str(formula_path),
                                "gc.work_dir": str(launcher),
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env.update(FORMULA_SOURCE=str(formula_path), REQUEST_JSON=str(request_path))
            result = subprocess.run(
                command,
                cwd=launcher,
                env=env,
                executable="/bin/sh",
                shell=True,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            self.assertTrue(json.loads(result.stdout)["ok"])
            self.assertEqual(run_git(worktree, "rev-parse", "HEAD"), base_commit)


if __name__ == "__main__":
    unittest.main()
