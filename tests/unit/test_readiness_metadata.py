from __future__ import annotations

import json

import pytest

from agent_fleet.adapters.repository.readiness_metadata import MetadataCapture


def test_python_static_declarations_include_groups_without_resolution() -> None:
    capture = MetadataCapture()
    capture.observe(
        "pyproject.toml",
        "pyproject.toml",
        """
[project]
requires-python = ">=3.12"
dependencies = ["requests>=2", "platformdirs; python_version > '3.10'"]
dynamic = ["version"]
[project.optional-dependencies]
test = ["pytest>=8"]
[dependency-groups]
lint = ["ruff>=0.6", {include-group = "test"}]
""",
    )
    report = capture.finish()
    names = {item.name for item in report.declarations}
    assert {"requests", "platformdirs", "pytest", "ruff"} <= names
    assert (
        next(item for item in report.declarations if item.category == "requires_python").constraint
        == ">=3.12"
    )
    assert next(item for item in report.declarations if item.name == "ruff").group == "lint"
    assert {item.code for item in report.diagnostics} == {
        "unsupported_metadata",
        "dynamic_declaration",
    }
    assert "python_version" not in report.model_dump_json()


def test_node_declarations_exclude_script_bodies() -> None:
    capture = MetadataCapture()
    capture.observe(
        "package.json",
        "package.json",
        json.dumps(
            {
                "packageManager": "pnpm@9.0.0",
                "engines": {"node": ">=20"},
                "dependencies": {"@scope/core": "^1"},
                "devDependencies": {"vitest": "^3"},
                "optionalDependencies": {"optional": "*"},
                "scripts": {"test": "NEVER_RETAIN_SCRIPT_BODY"},
            }
        ),
    )
    report = capture.finish()
    assert not report.diagnostics
    assert {item.category for item in report.declarations} == {
        "package_manager",
        "engine",
        "dependency",
        "dev_dependency",
        "optional_dependency",
    }
    assert "NEVER_RETAIN_SCRIPT_BODY" not in report.model_dump_json()


def test_python_extras_and_uv_source_overrides_are_not_silently_complete() -> None:
    capture = MetadataCapture()
    capture.observe(
        "pyproject.toml",
        "pyproject.toml",
        """
[project]
dependencies = ["requests[security]>=2"]
[tool.uv.sources]
requests = {git = "https://user:PRIVATE@host/repo"}
""",
    )
    report = capture.finish()
    assert [item.code for item in report.diagnostics] == [
        "unsupported_metadata",
        "unsupported_metadata",
    ]
    assert "PRIVATE" not in report.model_dump_json()


@pytest.mark.parametrize(
    ("value", "source"),
    [
        ("https://user:PRIVATE@host/a.tgz", "url"),
        ("git+https://user:PRIVATE@host/repo", "vcs"),
        ("file:../PRIVATE", "path"),
        ("workspace:PRIVATE", "workspace"),
        ("github:PRIVATE/repo", "vcs"),
    ],
)
def test_non_registry_payloads_are_never_retained(value: str, source: str) -> None:
    capture = MetadataCapture()
    capture.observe("package.json", "package.json", json.dumps({"dependencies": {"pkg": value}}))
    report = capture.finish()
    assert report.declarations[0].source_type == source
    assert report.declarations[0].constraint is None
    assert "PRIVATE" not in report.model_dump_json()
    assert report.diagnostics[0].code == "unsupported_dependency_source"


def test_python_direct_url_retains_only_normalized_package_name() -> None:
    capture = MetadataCapture()
    capture.observe(
        "pyproject.toml",
        "pyproject.toml",
        '[project]\ndependencies=["SafeName @ https://user:PRIVATE@host/a.whl"]',
    )
    declaration = capture.finish().declarations[0]
    assert declaration.name == "SafeName"
    assert declaration.source_type == "url"
    assert "PRIVATE" not in capture.finish().model_dump_json()


@pytest.mark.parametrize(
    "data",
    [
        {"engines": []},
        {"packageManager": "https://PRIVATE:PASS@host"},
        {"dependencies": []},
        {"dependencies": {"a": 42}},
        {"dependencies": {"invalid:PRIVATE": "1"}},
        {"engines": {"node": "https://PRIVATE"}},
    ],
)
def test_malformed_node_metadata_has_fixed_diagnostics_only(data: dict[str, object]) -> None:
    capture = MetadataCapture()
    capture.observe("package.json", "package.json", json.dumps(data))
    report = capture.finish()
    assert report.diagnostics
    assert "PRIVATE" not in report.model_dump_json()


def test_capture_limits_are_aggregate_and_explicit() -> None:
    capture = MetadataCapture()
    capture.observe(
        "package.json",
        "package.json",
        json.dumps({"dependencies": {f"dependency{i}": "1" for i in range(700)}}),
    )
    for i in range(70):
        capture.observe(f"p{i}/package.json", "package.json", "{}")
    report = capture.finish()
    assert len(report.manifests) == 64
    assert report.omitted_manifests == 7
    assert len(report.declarations) == 512
    assert report.omitted_declarations == 188
    assert len(report.diagnostics) == 128
    assert report.omitted_diagnostics > 0


@pytest.mark.parametrize("value", ["PRIVATE invalid JSON", '{"a":', "[[[[[[["])
def test_capture_parse_errors_never_preserve_exception_text(value: str) -> None:
    capture = MetadataCapture()
    capture.observe("package.json", "package.json", value)
    assert capture.finish().diagnostics[0].code == "metadata_capture_failed"
    assert "PRIVATE" not in capture.finish().model_dump_json()
