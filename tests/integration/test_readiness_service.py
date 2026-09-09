from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import agent_fleet.bootstrap as bootstrap
import agent_fleet.cli.app as cli_module
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_readiness_service
from agent_fleet.cli.readiness import _wire_size
from agent_fleet.domain.readiness import MAX_READINESS_BYTES, ReadinessReport
from agent_fleet.domain.security import Redactor


def _repository(tmp_path: Path) -> Path:
    root = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "repo"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nrequires-python=">=3.12"\ndependencies=["pytest>=8"]\n'
    )
    return root


def _files(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }


def _forbid(*args: object, **kwargs: object) -> None:
    raise AssertionError("static readiness must not construct an execution dependency")


def test_public_readiness_does_not_construct_or_write_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    state_root = tmp_path / "state-does-not-exist"
    before = _files(repository)
    monkeypatch.setenv("AGENT_FLEET_HOME", str(state_root))
    monkeypatch.setattr(cli_module, "build_container", _forbid)
    for name in (
        "SqliteStateStore",
        "RuntimeRegistry",
        "DockerSandboxProvider",
        "EnvironmentSecretStore",
        "LocalSystemDiagnostics",
    ):
        monkeypatch.setattr(bootstrap, name, _forbid)
    result = CliRunner().invoke(cli_module.app, ["readiness", str(repository), "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)["data"]
    assert report["inspection_complete"] is True
    assert report["baseline_status"] == "not_checked"
    assert report["environment_status"] == "unverified"
    assert report["commands_executed"] == 0
    assert not state_root.exists()
    assert not (repository / ".fleet").exists()
    assert _files(repository) == before


def test_config_snapshot_and_detected_candidates_remain_separate(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    config = YamlConfigurationAdapter()
    files = config.default_files("sample", StaticRepositoryProfiler().profile(repository).profile)
    config.apply(repository / ".fleet", files)
    before = _files(repository)
    report = build_readiness_service(state_root=tmp_path / "unused").inspect(repository)
    assert report.configuration_status == "valid"
    assert report.config_snapshot_sha256
    assert report.detected_candidates and report.configured_commands
    assert all(item.confidence is None for item in report.configured_commands)
    assert all(item.confidence is not None for item in report.detected_candidates)
    assert all(
        not item.execution_authorized
        for item in (*report.detected_candidates, *report.configured_commands)
    )
    assert _files(repository) == before


@pytest.mark.parametrize("kind", ["missing", "malformed", "symlink", "file", "entry_symlink"])
def test_invalid_existing_configuration_is_reported_not_defaulted(
    tmp_path: Path, kind: str
) -> None:
    repository = _repository(tmp_path)
    target = repository / ".fleet"
    if kind == "symlink":
        target.symlink_to(tmp_path / "absent", target_is_directory=True)
    elif kind == "file":
        target.write_text("PRIVATE")
    else:
        target.mkdir()
        if kind == "malformed":
            (target / "fleet.yaml").write_text("PRIVATE: [invalid")
        elif kind == "entry_symlink":
            outside = tmp_path / "outside"
            outside.write_text("PRIVATE")
            (target / "fleet.yaml").symlink_to(outside)
    result = CliRunner().invoke(cli_module.app, ["readiness", str(repository), "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)["data"]
    assert data["configuration_status"] == "invalid"
    assert data["config_snapshot_sha256"] is None
    assert data["configured_commands"] == []
    assert data["inspection_complete"] is False
    assert "PRIVATE" not in result.output


def test_node_static_report_has_no_dependency_installation_claim(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "pyproject.toml").unlink()
    (repository / "package.json").write_text(
        json.dumps(
            {
                "packageManager": "npm@10.0.0",
                "engines": {"node": ">=20"},
                "devDependencies": {"vitest": "^3"},
                "scripts": {"test": "NEVER_EXECUTE_BODY"},
            }
        )
    )
    (repository / "package-lock.json").write_text("PRIVATE LOCK BODY NOT JSON")
    report = build_readiness_service(state_root=tmp_path / "unused").inspect(repository)
    assert report.inspection_complete
    assert report.ecosystems == ("node",)
    assert report.lock_files == ("package-lock.json",)
    assert report.detected_candidates[0].argv == ("run", "test")
    assert report.environment_status == "unverified"
    assert report.baseline_status == "not_checked"
    assert "PRIVATE" not in report.model_dump_json()
    assert "NEVER_EXECUTE_BODY" not in report.model_dump_json()


def test_parser_and_registered_secret_projection_are_safe(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "package.json").write_text('{"PRIVATE:password": [INVALID')
    (repository / "pyproject.toml").write_text('[project]\ndependencies=["PRIVATE"]\n')
    report = build_readiness_service(
        redactor=Redactor(["PRIVATE"]), state_root=tmp_path / "unused"
    ).inspect(repository)
    assert not report.inspection_complete
    assert "PRIVATE" not in report.model_dump_json()
    assert "INVALID" not in report.model_dump_json()
    assert report.metadata.omitted_declarations == 1


def test_human_output_explicitly_disclaims_execution(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    result = CliRunner().invoke(cli_module.app, ["readiness", str(repository)])
    assert result.exit_code == 0
    assert "Static inspection only" in result.output
    assert "baseline not checked" in result.output
    assert "no project commands executed" in result.output


@pytest.mark.parametrize(
    "args",
    [["--run", "https://PRIVATE:PASS@host"], ["--prepare"], ["--verify"], ["one", "PRIVATE"]],
)
def test_invalid_readiness_arguments_are_safe_exit_two(args: list[str]) -> None:
    result = CliRunner().invoke(cli_module.app, ["readiness", *args, "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["ok"] is False
    assert "PRIVATE" not in result.output


def test_unsafe_repository_admission_is_safe_exit_two(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli_module.app, ["readiness", str(tmp_path / "PRIVATE"), "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["ok"] is False
    assert "PRIVATE" not in result.output


def test_public_unicode_report_respects_actual_json_envelope_byte_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    (repository / "pyproject.toml").unlink()
    nested = repository
    for index in range(5):
        component = "界" * 45 + str(index)
        assert len(component.encode("utf-8")) < 255
        nested /= component
        nested.mkdir()
    for index in range(64):
        package = nested / f"package{index:02}"
        package.mkdir()
        manifest = package / "package.json"
        assert len(manifest.relative_to(repository).parts) <= 12
        manifest.write_text(
            json.dumps(
                {
                    "packageManager": "npm@10.0.0",
                    "dependencies": {f"dependency{i}": "^1" for i in range(8)},
                    "scripts": {"test": "NEVER_EXECUTE_SCRIPT"},
                }
            )
        )
    before = _files(repository)
    state_root = tmp_path / "absent-state"
    monkeypatch.setenv("AGENT_FLEET_HOME", str(state_root))
    result = CliRunner().invoke(cli_module.app, ["readiness", str(repository), "--json"])
    assert result.exit_code == 1, result.output
    assert len(result.stdout.encode("utf-8")) <= MAX_READINESS_BYTES
    assert result.stdout.endswith("\n")
    data = json.loads(result.stdout)["data"]
    assert _wire_size(data, Redactor()) == len(result.stdout.encode("utf-8"))
    report = ReadinessReport.model_validate_json(json.dumps(data))
    assert not report.inspection_complete
    assert any(item.code == "report_byte_limit" for item in report.diagnostics)
    assert report.omitted_commands > 0
    assert report.baseline_status == "not_checked"
    assert report.environment_status == "unverified"
    assert report.commands_executed == 0
    assert "NEVER_EXECUTE_SCRIPT" not in result.stdout
    assert _files(repository) == before
    assert not state_root.exists()
