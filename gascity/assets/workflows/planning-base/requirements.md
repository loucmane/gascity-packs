This is the `planning-base` methodology contract requirements step.

Concrete methodology packs override this step to produce their native
requirements artifact. Write the approved requirements to `{{requirements_path}}`
when it is provided, or record the resolved requirements path on workflow root
metadata as `gc.build.requirements_path` before closing.

Artifact validation: the controller executes the authoritative validation gate from the controller-stamped absolute `gc.check_path`, which validates the artifact recorded at `gc.build.requirements_path` (fallback `gc.var.requirements_path`) against schema `gc.build.requirements.v1`. Do not run this validator from the worker; the controller records failures in `gc.attempt_log` for the bounded retry. On repair attempts (`gc.attempt` greater than 1), read the validator errors from `gc.attempt_log` on the validation loop control bead (the dependent of this step bead) and repair the artifact in place instead of rewriting it. Two bounded repair attempts follow the first failure; exhausting them closes this stage with `gc.outcome=fail` and machine-readable validation errors that block downstream stages. Never ask questions in headless mode; record unresolved ambiguity inside the artifact.
