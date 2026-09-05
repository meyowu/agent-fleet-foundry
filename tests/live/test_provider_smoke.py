from __future__ import annotations

import base64
import json
import os
import socket
from pathlib import Path
from typing import cast
from urllib.parse import quote, quote_plus

import pydantic_ai.models as pydantic_ai_models
import pytest
from typer.testing import CliRunner

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.cli.app import app
from agent_fleet.ports.secret_store import SecretRef

_LIVE_PROVIDER_MODEL = "AGENT_FLEET_LIVE_PROVIDER_MODEL"
_LIVE_PROVIDER_CREDENTIAL_REF = "AGENT_FLEET_LIVE_PROVIDER_CREDENTIAL_REF"

_CANARY_GOAL = (
    "Use the engineer_verifier code-change workflow and modify only "
    "src/canary_calc/core.py. Replace that file with a valid Python module containing the "
    "existing divide(a, b) function plus an explicit b == 0 guard that raises "
    'ValueError("division by zero is not allowed"). The Engineer must call '
    "workspace_write_file with the complete file content, then call run_verification. The "
    "independent Verifier must call run_verification and assess this criterion. Require "
    "canonical_patch, command_evidence, and independent_verifier_verdict evidence. Do not "
    "modify .fleet or any other path."
)


def _credential_forms(secret: str) -> tuple[bytes, ...]:
    encoded = secret.encode("utf-8")
    standard_base64 = base64.b64encode(encoded).decode("ascii")
    urlsafe_base64 = base64.urlsafe_b64encode(encoded).decode("ascii")
    json_escaped = json.dumps(secret, ensure_ascii=True)[1:-1]
    text_forms = {
        secret,
        quote(secret, safe=""),
        quote_plus(secret, safe=""),
        standard_base64,
        standard_base64.rstrip("="),
        urlsafe_base64,
        urlsafe_base64.rstrip("="),
        encoded.hex(),
        json_escaped,
    }
    return tuple(
        sorted(
            {item.encode("utf-8") for item in text_forms if item},
            key=len,
            reverse=True,
        )
    )


def _assert_no_credential_leak(
    payload: bytes,
    forms: tuple[bytes, ...],
    location: str,
) -> None:
    if any(form in payload for form in forms):
        pytest.fail(f"provider credential leak detected in {location}", pytrace=False)


def _assert_tree_has_no_credential_leak(
    root: Path,
    forms: tuple[bytes, ...],
) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            pytest.fail(
                "could not inspect a disposable canary file for credential leaks",
                pytrace=False,
            )
        _assert_no_credential_leak(content, forms, "disposable repository or Fleet state")


def _invoke_json(
    runner: CliRunner,
    arguments: list[str],
    environment: dict[str, str],
    forms: tuple[bytes, ...],
) -> object:
    result = runner.invoke(app, arguments, env=environment)
    captured = result.stdout_bytes + (result.stderr_bytes or b"")
    _assert_no_credential_leak(captured, forms, "CLI output")
    if result.exception is not None:
        _assert_no_credential_leak(
            _exception_chain_bytes(result.exception),
            forms,
            "CLI exception",
        )
    if result.exit_code != 0:
        pytest.fail("live provider CLI canary failed with a redacted diagnostic", pytrace=False)
    try:
        envelope = json.loads(result.stdout)
    except (TypeError, ValueError):
        pytest.fail("live provider CLI canary returned invalid JSON", pytrace=False)
    if not isinstance(envelope, dict) or envelope.get("ok") is not True:
        pytest.fail("live provider CLI canary returned an unsuccessful envelope", pytrace=False)
    return envelope.get("data")


def _exception_chain_bytes(error: BaseException) -> bytes:
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.extend((type(current).__name__, str(current), repr(current)))
        current = current.__cause__ or current.__context__
    return "\n".join(parts).encode("utf-8", errors="replace")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        pytest.fail(f"live provider canary returned invalid {label}", pytrace=False)
    return cast(dict[str, object], value)


def _items(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        pytest.fail(f"live provider canary returned invalid {label}", pytrace=False)
    return cast(list[object], value)


def test_ordinary_suite_denies_network_and_live_model_requests() -> None:
    assert pydantic_ai_models.ALLOW_MODEL_REQUESTS is False
    with pytest.raises(AssertionError, match="must not perform network access"):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(AssertionError, match="must not perform network access"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.01)


@pytest.mark.live_provider
@pytest.mark.docker_integration
def test_live_provider_cli_cos_engineer_verifier_canary(
    tmp_path: Path,
    real_docker_image: str,
) -> None:
    provider_model = os.environ[_LIVE_PROVIDER_MODEL]
    credential_ref = os.environ[_LIVE_PROVIDER_CREDENTIAL_REF]
    credential_name = SecretRef.parse(credential_ref).name
    credential = os.environ[credential_name]
    if len(credential.encode("utf-8")) < 16:
        pytest.fail("live provider credential must be at least 16 bytes", pytrace=False)
    forms = _credential_forms(credential)

    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator()).create_canary_fixture(
        tmp_path / "live-provider-repository"
    )
    manifest = repository / "pyproject.toml"
    manifest.write_text(
        manifest.read_text() + "\n[tool.pytest.ini_options]\npythonpath = ['src']\n"
    )
    git = GitRepositoryAdapter(tmp_path, UuidIdGenerator())
    git._run(["git", "add", "--", "pyproject.toml"], cwd=repository)
    git._run(
        ["git", "commit", "--no-gpg-sign", "--no-verify", "-m", "Declare canary import path"],
        cwd=repository,
    )
    state_root = tmp_path / "live-provider-state"
    environment = {"AGENT_FLEET_HOME": str(state_root)}
    runner = CliRunner()

    initialized = _mapping(
        _invoke_json(
            runner,
            [
                "init",
                str(repository),
                "--runtime",
                "pydantic-ai",
                "--provider-model",
                provider_model,
                "--credential-ref",
                credential_ref,
                "--sandbox",
                "docker",
                "--docker-image",
                real_docker_image,
                "--yes",
                "--json",
            ],
            environment,
            forms,
        ),
        "initialization data",
    )
    assert initialized["runtime"] == "pydantic-ai"
    assert initialized["provider_model"] == provider_model
    assert initialized["sandbox"] == "docker"
    assert initialized["security_level"] == "isolated"
    assert initialized["bootstrap_verified"] is True
    assert initialized["bootstrap_cleanup_complete"] is True

    executed = _mapping(
        _invoke_json(
            runner,
            [
                "run",
                _CANARY_GOAL,
                "--project",
                str(repository),
                "--runtime",
                "pydantic-ai",
                "--provider-model",
                provider_model,
                "--credential-ref",
                credential_ref,
                "--sandbox",
                "docker",
                "--json",
            ],
            environment,
            forms,
        ),
        "run data",
    )
    run_id = executed.get("run_id")
    if not isinstance(run_id, str):
        pytest.fail("live provider canary did not return a run ID", pytrace=False)

    # Explicitly opted-in disposable test approves only each observed exact request.
    for _ in range(12):
        if executed["status"] != "paused_for_approval":
            break
        request_id = executed.get("pending_approval_id")
        assert isinstance(request_id, str)
        _invoke_json(runner, ["permissions", "explain", request_id, "--json"], environment, forms)
        _invoke_json(runner, ["approve", request_id, "--run", "--json"], environment, forms)
        executed = _mapping(
            _invoke_json(runner, ["resume", run_id, "--json"], environment, forms), "resume data"
        )
    assert executed["status"] == "ready_for_review"

    status = _mapping(
        _invoke_json(runner, ["status", run_id, "--json"], environment, forms),
        "status data",
    )
    log_items = _items(
        _invoke_json(runner, ["logs", run_id, "--json"], environment, forms),
        "event history",
    )
    artifact_items = _items(
        _invoke_json(runner, ["artifacts", run_id, "--json"], environment, forms),
        "artifact metadata",
    )

    assert status["status"] == "ready_for_review"
    assert status["runtime"] == "pydantic-ai"
    assert status["provider_model"] == provider_model
    assert status["fleet_strategy"] == "engineer_verifier"
    assert status["sandbox"] == "docker"
    assert status["security_level"] == "isolated"
    assert status["verified_complete"] is True

    evidence = _mapping(status.get("evidence"), "evidence")
    assert evidence["verified_complete"] is True
    assert evidence["proof_gaps"] == []
    reason_codes = _items(evidence.get("completion_reason_codes"), "completion reasons")
    assert "SIMULATED_EVIDENCE_ONLY" not in reason_codes
    command_results = _items(evidence.get("command_results"), "command evidence")
    assert len(command_results) >= 2
    for result in command_results:
        command = _mapping(result, "command evidence item")
        assert command["strength"] in {"observed", "independently_verified"}
        assert command["sandbox_provider"] == "docker"
        assert command["sandbox_security_level"] == "isolated"
        assert command["exit_code"] == 0
        assert command["sandbox_inspection_artifact_id"] is not None

    completed_roles: list[object] = []
    for event_value in log_items:
        event = _mapping(event_value, "event")
        payload = event.get("payload")
        if event.get("event_type") == "agent.completed" and isinstance(payload, dict):
            completed_roles.append(payload.get("role"))
    assert completed_roles[0] == "cos" and completed_roles.count("cos") == 1
    assert completed_roles.index("engineer") < completed_roles.index("verifier")

    usage_ids = _items(status.get("runtime_usage_artifact_ids"), "runtime usage bindings")
    assert len(usage_ids) >= 3
    container = build_container(state_root)
    usage_roles: list[str] = []
    for artifact_id in usage_ids:
        assert isinstance(artifact_id, str)
        observation = json.loads(container.artifacts.read_text(artifact_id))
        _assert_no_credential_leak(
            json.dumps(observation, sort_keys=True).encode("utf-8"),
            forms,
            "runtime usage artifact",
        )
        observation_data = _mapping(observation, "runtime usage artifact")
        role = observation_data.get("role")
        assert isinstance(role, str)
        usage_roles.append(role)
        usage = _mapping(observation_data.get("usage"), "runtime usage record")
        requests = usage.get("requests")
        total_tokens = usage.get("total_tokens")
        assert isinstance(requests, int) and requests >= 1
        assert isinstance(total_tokens, int) and total_tokens > 0
    assert usage_roles[0] == "cos" and {"cos", "engineer", "verifier"} <= set(usage_roles)
    assert not container.state.outstanding_leases()

    artifact_kinds = {
        _mapping(item, "artifact metadata item").get("kind") for item in artifact_items
    }
    assert {
        "task_spec",
        "implementation_report",
        "patch",
        "command_evidence",
        "verifier_verdict",
        "evidence_bundle",
        "runtime_usage",
    } <= artifact_kinds

    serialized_observations = json.dumps(
        {"status": status, "logs": log_items, "artifacts": artifact_items},
        sort_keys=True,
    ).encode("utf-8")
    _assert_no_credential_leak(serialized_observations, forms, "application inspection data")
    _assert_tree_has_no_credential_leak(repository, forms)
    _assert_tree_has_no_credential_leak(state_root, forms)
