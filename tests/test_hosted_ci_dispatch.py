from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PORTABLE_RUNNER = (
    "${{ github.repository_owner == 'gastownhall' && "
    "'blacksmith-32vcpu-ubuntu-2404' || 'ubuntu-latest' }}"
)


def _workflow(path: str) -> dict:
    return yaml.load(
        (ROOT / path).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )


def _workflow_events(path: str) -> set[str]:
    return set(_workflow(path)["on"])


def test_ci_supports_automatic_and_manual_runs() -> None:
    assert _workflow_events(".github/workflows/ci.yml") == {
        "pull_request",
        "push",
        "workflow_dispatch",
    }


def test_codeql_supports_automatic_scheduled_and_manual_runs() -> None:
    assert _workflow_events(".github/workflows/codeql.yml") == {
        "pull_request",
        "push",
        "schedule",
        "workflow_dispatch",
    }


def test_ci_uses_upstream_runner_with_hosted_fork_fallback() -> None:
    assert _workflow(".github/workflows/ci.yml")["jobs"]["check"]["runs-on"] == PORTABLE_RUNNER


def test_codeql_uses_upstream_runner_with_hosted_fork_fallback() -> None:
    assert _workflow(".github/workflows/codeql.yml")["jobs"]["analyze"]["runs-on"] == PORTABLE_RUNNER
