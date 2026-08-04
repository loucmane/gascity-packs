from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_OPEN_VOCABULARY_ROLES = {
    "design-author",
    "design-implementation-reviewer",
    "design-test-risk-reviewer",
    "gap-analyst",
    "implementation-reviewer",
    "implementation-worker",
    "issue-triager",
    "publisher",
    "requirements-planner",
    "review-synthesizer",
    "run-operator",
    "task-decomposer",
}


class ManagedRoleClaimProtocolTests(unittest.TestCase):
    def test_every_imported_role_uses_the_simple_native_claim_protocol(self) -> None:
        prompts = {
            path.parent.name: path
            for path in sorted((ROOT / "roles" / "agents").glob("*/prompt.template.md"))
        }
        self.assertEqual(set(prompts), EXPECTED_OPEN_VOCABULARY_ROLES)

        for role, path in prompts.items():
            text = path.read_text(encoding="utf-8")
            self.assertIn("`gc hook --claim --json`", text, role)
            self.assertIn("`bd show <claimed-bead-id> --json`", text, role)
            self.assertIn("`gc runtime drain-ack`", text, role)
            self.assertNotIn("GC_CLAIM", text, role)
            self.assertNotIn("bash <<", text, role)
            self.assertNotIn("&&", text, role)

    def test_all_render_sources_carry_the_same_claim_protocol(self) -> None:
        sources = [
            ROOT / "roles" / "prompts" / "shared" / "gc-role-worker.md.tmpl",
            ROOT / "roles" / "template-fragments" / "gc-role-worker.template.md",
            ROOT / "template-fragments" / "gc-role-worker.template.md",
        ]
        rendered = [path.read_text(encoding="utf-8") for path in sources]
        self.assertTrue(all(text == rendered[0] for text in rendered[1:]))

        for text in rendered:
            self.assertIn("`gc hook --claim --json`", text)
            self.assertIn("`bd show <claimed-bead-id> --json`", text)
            self.assertIn("`gc runtime drain-ack`", text)
            self.assertIn("exact validator path and SHA-256", text)
            self.assertNotIn("GC_CLAIM", text)
            self.assertNotIn("bash <<", text)


if __name__ == "__main__":
    unittest.main()
