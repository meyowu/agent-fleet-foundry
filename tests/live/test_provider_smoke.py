from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import cast

import pydantic_ai.models as pydantic_ai_models
import pytest
from live_provider_support import (
    EVIDENCE_DIRECTORY_ENV,
    PROFILE_LIMITS,
    ROOT_LIMITS,
    CanaryEvidence,
    assert_live_canary_verification,
    credential_forms,
    prepare_live_canary_fixture,
)
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
    return credential_forms(secret)


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
    recorder: CanaryEvidence,
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
    try:
        envelope = json.loads(result.stdout)
    except (TypeError, ValueError):
        pytest.fail("live provider CLI canary returned invalid JSON", pytrace=False)
    recorder.cli_observations.append({"exit_code": result.exit_code, "envelope": envelope})
    if result.exit_code != 0:
        pytest.fail(
            "live provider CLI canary failed; inspect retained safe envelope", pytrace=False
        )
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
    request: pytest.FixtureRequest,
) -> None:
    provider_model = os.environ[_LIVE_PROVIDER_MODEL]
    credential_ref = os.environ[_LIVE_PROVIDER_CREDENTIAL_REF]
    credential_name = SecretRef.parse(credential_ref).name
    credential = os.environ[credential_name]
    if len(credential.encode("utf-8")) < 16:
        pytest.fail("live provider credential must be at least 16 bytes", pytrace=False)
    forms = _credential_forms(credential)

    state_root = tmp_path / "live-provider-state"
    evidence_directory = os.environ.get(EVIDENCE_DIRECTORY_ENV)
    recorder = CanaryEvidence(
        state_root=state_root,
        repository=tmp_path / "live-provider-repository",
        forms=forms,
        directory=Path(evidence_directory) if evidence_directory else None,
        selected_model=provider_model,
    )
    # CliRunner owns synchronous invocations: every call has exited before teardown.
    # Register before init so bootstrap failures also retain evidence and clean leases.
    request.addfinalizer(recorder.finish)

    def invoke(
        runner: CliRunner,
        arguments: list[str],
        environment: dict[str, str],
        forms: tuple[bytes, ...],
    ) -> object:
        return _invoke_json(runner, arguments, environment, forms, recorder)

    repository = prepare_live_canary_fixture(tmp_path / "live-provider-repository")
    git = GitRepositoryAdapter(tmp_path, UuidIdGenerator())
    original_source = (repository / "src/canary_calc/core.py").read_bytes()
    environment = {"AGENT_FLEET_HOME": str(state_root)}
    runner = CliRunner()

    initialized = _mapping(
        invoke(
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
    assert_live_canary_verification(repository)

    invoke(
        runner,
        [
            "models",
            "set",
            "live-canary",
            "--runtime",
            "pydantic-ai",
            "--provider-model",
            provider_model,
            "--credential-ref",
            credential_ref,
            *[
                argument
                for name, value in PROFILE_LIMITS.items()
                for argument in ("--" + name.replace("_", "-"), str(value))
            ],
            "--json",
        ],
        environment,
        forms,
    )
    invoke(
        runner,
        ["models", "bind", "live-canary", "--path", str(repository), "--default", "--json"],
        environment,
        forms,
    )
    baseline = git.inspect(repository)

    executed = _mapping(
        invoke(
            runner,
            [
                "run",
                _CANARY_GOAL,
                "--project",
                str(repository),
                "--sandbox",
                "docker",
                *[
                    argument
                    for name, value in ROOT_LIMITS.items()
                    for argument in ("--" + name.replace("_", "-"), str(value))
                ],
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
        invoke(runner, ["permissions", "explain", request_id, "--json"], environment, forms)
        invoke(runner, ["approve", request_id, "--run", "--json"], environment, forms)
        executed = _mapping(
            invoke(runner, ["resume", run_id, "--json"], environment, forms), "resume data"
        )
    assert executed["status"] == "ready_for_review"

    status = _mapping(
        invoke(runner, ["status", run_id, "--json"], environment, forms),
        "status data",
    )
    log_items = _items(
        invoke(runner, ["logs", run_id, "--json"], environment, forms),
        "event history",
    )
    artifact_items = _items(
        invoke(runner, ["artifacts", run_id, "--json"], environment, forms),
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
    assert evidence["changed_paths"] == ["src/canary_calc/core.py"]
    assert (repository / "src/canary_calc/core.py").read_bytes() == original_source
    final_repository = git.inspect(repository)
    assert final_repository.head_revision == baseline.head_revision
    assert final_repository.status_fingerprint == baseline.status_fingerprint

    budget = _mapping(status.get("runtime_budget"), "runtime budget")
    assert budget["limits"] == ROOT_LIMITS
    assert budget["completeness"] == "complete"
    for name in ("reserved_tokens", "unknown_tokens", "outstanding_requests", "unknown_requests"):
        assert budget[name] == 0
    for usage_name, limit_name in (
        ("agent_invocations", "max_agent_invocations"),
        ("model_requests", "max_model_requests"),
        ("tool_calls", "max_tool_calls"),
        ("reported_total_tokens", "max_total_tokens"),
        ("active_seconds", "max_active_seconds"),
    ):
        used = budget[usage_name]
        assert isinstance(used, (int, float)) and 0 < used <= ROOT_LIMITS[limit_name]
    bindings = _mapping(status.get("model_bindings"), "frozen model bindings")
    bound_roles = _mapping(bindings.get("roles"), "model role bindings")
    for bound_role in ("cos", "engineer", "verifier"):
        binding = _mapping(bound_roles.get(bound_role), "model binding")
        assert binding["profile_name"] == "live-canary" and binding["profile_revision"] == 1
        configuration = _mapping(binding.get("configuration"), "role configuration")
        assert configuration["runtime_name"] == "pydantic-ai"
        assert configuration["provider_model"] == provider_model
        for name, value in PROFILE_LIMITS.items():
            assert configuration[name] == value
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
    patch_id = status.get("patch_artifact_id")
    assert isinstance(patch_id, str)
    patch = container.artifacts.read_text(patch_id)
    assert [line for line in patch.splitlines() if line.startswith("diff --git ")] == [
        "diff --git a/src/canary_calc/core.py b/src/canary_calc/core.py"
    ]
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
        selected = _mapping(observation_data.get("selected_model"), "invoked model binding")
        assert selected["provider_model"] == provider_model
        assert selected["max_retries"] == PROFILE_LIMITS["max_retries"]
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
    recorder.passed = True
