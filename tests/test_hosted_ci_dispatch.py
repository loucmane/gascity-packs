from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _workflow_events(path: str) -> set[str]:
    document = yaml.load(
        (ROOT / path).read_text(encoding="utf-8"),
        Loader=yaml.BaseLoader,
    )
    return set(document["on"])


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
