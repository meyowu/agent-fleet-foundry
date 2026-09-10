from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_fleet.adapters.repository.profile as profile_module
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.repository.readiness_metadata import MetadataCapture
from agent_fleet.domain.repository_profile import ProjectKnowledge
from agent_fleet.domain.security import canonical_json_hash


def test_metadata_capture_preserves_profile_bytes_and_reads_each_manifest_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n')
    (tmp_path / "package.json").write_text('{"scripts":{"test":"PRIVATE SCRIPT"}}')
    (tmp_path / "package-lock.json").write_text("PRIVATE LOCK")
    profiler = StaticRepositoryProfiler()
    legacy = profiler.profile(tmp_path).model_dump_json()
    observed: list[str] = []
    original = profile_module._ReadBudget.read

    def read(budget: profile_module._ReadBudget, candidate: profile_module._Candidate) -> bytes:
        observed.append(candidate.relative)
        return original(budget, candidate)

    monkeypatch.setattr(profile_module._ReadBudget, "read", read)
    result, metadata = profiler.profile_with_metadata(tmp_path)
    assert result.model_dump_json() == legacy
    assert sorted(observed) == ["package.json", "pyproject.toml"]
    assert len(metadata.manifests) == 2
    assert "PRIVATE" not in metadata.model_dump_json()


def test_legacy_profile_does_not_create_metadata_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden() -> None:
        raise AssertionError("legacy profiling cannot instantiate metadata capture")

    monkeypatch.setattr(profile_module, "MetadataCapture", forbidden)
    assert StaticRepositoryProfiler().profile(tmp_path).profile.root == "."


def test_metadata_failure_does_not_change_legacy_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies=["pytest"]\n')
    profiler = StaticRepositoryProfiler()
    before = profiler.profile(tmp_path).model_dump_json()

    def failing(*args: object) -> None:
        raise ValueError("PRIVATE parser input")

    monkeypatch.setattr(MetadataCapture, "observe", failing)
    result, metadata = profiler.profile_with_metadata(tmp_path)
    assert result.model_dump_json() == before
    assert metadata.diagnostics[0].code == "metadata_capture_failed"
    assert "PRIVATE" not in metadata.model_dump_json()


def _commands(result: object) -> set[tuple[str, tuple[str, ...]]]:
    profile = result.profile  # type: ignore[attr-defined]
    return {(item.executable, tuple(item.argv)) for item in profile.commands}


def test_python_and_node_profiles_derive_commands_from_static_manifests(tmp_path: Path) -> None:
    python = tmp_path / "python"
    python.mkdir()
    (python / "pyproject.toml").write_text(
        """
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[project]
name = "demo"
dependencies = ["pytest>=8", "ruff>=0.6"]
[tool.uv]
managed = true
""".strip(),
        encoding="utf-8",
    )
    (python / "uv.lock").write_text("version = 1\n", encoding="utf-8")

    node = tmp_path / "node"
    node.mkdir()
    (node / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "pnpm@9.0.0",
                "scripts": {"test": "vitest run", "lint": "eslint .", "build": "vite build"},
            }
        ),
        encoding="utf-8",
    )
    (node / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    profiler = StaticRepositoryProfiler()
    python_result = profiler.profile(python)
    node_result = profiler.profile(node)

    assert python_result.profile.ecosystems == ["python"]
    assert ("uv", ("run", "pytest")) in _commands(python_result)
    assert ("uv", ("run", "ruff", "check", ".")) in _commands(python_result)
    assert ("uv", ("build",)) in _commands(python_result)
    assert node_result.profile.ecosystems == ["node"]
    assert ("pnpm", ("run", "test")) in _commands(node_result)
    assert all(not command.execution_authorized for command in node_result.profile.commands)
    assert all(
        command.provenance.path == "package.json" for command in node_result.profile.commands
    )


def test_poetry_group_dependencies_and_native_build_are_detected(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.poetry]
name = "demo"
version = "0.1.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
ruff = "^0.6"
mypy = "^1.11"
""".strip(),
        encoding="utf-8",
    )
    (tmp_path / "poetry.lock").write_text("package = []\n", encoding="utf-8")

    result = StaticRepositoryProfiler().profile(tmp_path)

    commands = _commands(result)
    assert ("poetry", ("run", "pytest")) in commands
    assert ("poetry", ("run", "ruff", "check", ".")) in commands
    assert ("poetry", ("run", "mypy")) in commands
    assert ("poetry", ("build",)) in commands


def test_manifest_change_changes_profile_and_source_profile_hash(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=['pytest']\n", encoding="utf-8"
    )
    profiler = StaticRepositoryProfiler()
    before = profiler.profile(tmp_path)

    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='demo'\ndependencies=['pytest', 'ruff']\n", encoding="utf-8"
    )
    after = profiler.profile(tmp_path)

    assert (
        before.project_knowledge.source_profile_sha256
        != after.project_knowledge.source_profile_sha256
    )
    assert ("ruff", ("check", ".")) not in _commands(before)
    assert ("ruff", ("check", ".")) in _commands(after)
    assert after.project_knowledge.source_profile_sha256 == canonical_json_hash(
        after.profile.model_dump(mode="json")
    )


def test_hooks_package_scripts_and_make_recipes_are_never_executed(tmp_path: Path) -> None:
    sentinel = tmp_path / "executed"
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {sentinel}\n", encoding="utf-8")
    hook.chmod(0o755)
    (tmp_path / "package.json").write_text(
        json.dumps(
            {
                "scripts": {
                    "postinstall": f"touch {sentinel}",
                    "test": f"touch {sentinel}",
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "Makefile").write_text(f"test:\n\ttouch {sentinel}\n", encoding="utf-8")

    result = StaticRepositoryProfiler().profile(tmp_path)

    assert not sentinel.exists()
    assert ("npm", ("run", "postinstall")) in _commands(result)
    assert ("make", ("test",)) in _commands(result)


def test_node_commands_are_omitted_when_package_manager_is_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}),
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("# yarn lockfile\n", encoding="utf-8")

    result = StaticRepositoryProfiler().profile(tmp_path)

    assert not result.profile.commands
    assert result.profile.ecosystems == ["node"]
    assert {"node", "pnpm", "yarn"}.issubset(result.profile.build_systems)
    assert any(item.code == "conflicting_node_lockfiles" for item in result.profile.ambiguities)


def test_symlinked_manifest_escape_is_ignored_without_reading_target(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    outside = tmp_path / "outside-package.json"
    outside.write_text(
        json.dumps({"scripts": {"stolen-secret-command": "echo secret"}}), encoding="utf-8"
    )
    (repository / "package.json").symlink_to(outside)

    result = StaticRepositoryProfiler().profile(repository)

    assert result.profile.ecosystems == []
    assert result.profile.files_read == []
    assert not result.profile.commands
    assert any(item.code == "symlink_ignored" for item in result.profile.ambiguities)


def test_profile_is_deterministic_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.test/demo\n\ngo 1.22\n", encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "ci.yaml").write_text(
        "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )

    profiler = StaticRepositoryProfiler()
    first = profiler.profile(tmp_path)
    second = profiler.profile(tmp_path)

    assert first == second
    assert (
        first.project_knowledge.source_profile_sha256
        == second.project_knowledge.source_profile_sha256
    )
    assert first.profile.ecosystems == ["github-actions", "go"]
    assert first.profile.files_read == sorted(first.profile.files_read)


def test_supported_build_signals_and_nested_boundaries_are_reported(tmp_path: Path) -> None:
    fixtures = {
        "service/go.mod": "module example.test/service\n",
        "crate/Cargo.toml": "[package]\nname='crate'\nversion='0.1.0'\n",
        "java/pom.xml": "<project><modelVersion>4.0.0</modelVersion></project>\n",
        "android/build.gradle.kts": "plugins { java }\n",
        "tools/Makefile": "lint:\n\t@echo lint\n",
        ".github/workflows/ci.yml": (
            "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        ),
    }
    for relative, content in fixtures.items():
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    result = StaticRepositoryProfiler().profile(tmp_path)

    assert result.profile.ecosystems == [
        "github-actions",
        "go",
        "gradle",
        "make",
        "maven",
        "rust",
    ]
    boundaries = {item.path for item in result.profile.boundaries}
    assert boundaries == {".", "android", "crate", "java", "service", "tools"}
    assert ("go", ("test", "./...")) in _commands(result)
    assert ("cargo", ("test",)) in _commands(result)
    assert ("mvn", ("test",)) in _commands(result)
    assert ("gradle", ("test",)) in _commands(result)
    assert ("make", ("lint",)) in _commands(result)


def test_conflicting_lockfiles_and_parse_failures_are_ambiguities(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("{not-json", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project\n", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (tmp_path / "poetry.lock").write_text("", encoding="utf-8")

    result = StaticRepositoryProfiler().profile(tmp_path)
    codes = {item.code for item in result.profile.ambiguities}

    assert "conflicting_node_lockfiles" in codes
    assert "conflicting_python_lockfiles" in codes
    assert "manifest_parse_failed" in codes


def test_global_read_budget_skips_oversized_regular_file(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_bytes(b" " * 512_001)

    result = StaticRepositoryProfiler().profile(tmp_path)

    assert result.profile.bytes_read == 0
    assert result.profile.files_read == []
    assert any(item.code == "read_budget_exceeded" for item in result.profile.ambiguities)


def test_deeply_nested_workflow_is_reported_as_parse_ambiguity(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "deep.yml").write_text(
        "jobs: " + "[" * 650 + "0" + "]" * 650 + "\n",
        encoding="utf-8",
    )

    result = StaticRepositoryProfiler().profile(tmp_path)

    assert any(
        item.code == "manifest_parse_failed" and item.paths == [".github/workflows/deep.yml"]
        for item in result.profile.ambiguities
    )


def test_project_knowledge_accepts_legacy_source_hash_name_but_serializes_precisely() -> None:
    knowledge = ProjectKnowledge.model_validate(
        {
            "knowledge_hash": "a" * 64,
            "summary": "No supported ecosystem detected.",
            "ecosystems": [],
            "build_systems": [],
            "repository_boundaries": [],
            "verification_commands": [],
            "ambiguities": [],
        }
    )

    assert knowledge.source_profile_sha256 == "a" * 64
    serialized = knowledge.model_dump(mode="json")
    assert serialized["source_profile_sha256"] == "a" * 64
    assert "knowledge_hash" not in serialized
