"""Registered real Git/SQLite/guards/Gateway with an offline Docker transport only."""

import asyncio
import sqlite3
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from test_baseline_sandbox import BaselineRecordingRunner
else:
    from contract.test_baseline_sandbox import BaselineRecordingRunner

import agent_fleet.bootstrap as bootstrap
from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.sandbox.docker import DockerSandboxProvider
from agent_fleet.adapters.sandbox.process import ProcessResult
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.application.baseline import baseline_exit_code
from agent_fleet.bootstrap import BaselineContainer, build_baseline_container
from agent_fleet.domain.baseline import BaselineCommandObservation
from agent_fleet.domain.baseline_resources import (
    BaselineOwnerClaim,
    BaselineSandboxHandle,
    BaselineWorkspace,
)
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.models import Project, SandboxConfiguration
from agent_fleet.domain.security import Redactor, sha256_bytes


def business_fixture(
    tmp_path: Path,
    *,
    redactor: Redactor | None = None,
) -> tuple[BaselineContainer, Path, str, BaselineRecordingRunner]:
    repository = GitRepositoryAdapter(tmp_path, UuidIdGenerator())
    root = repository.create_canary_fixture(tmp_path / "project")
    config = YamlConfigurationAdapter()
    profile = StaticRepositoryProfiler().profile(root).profile
    config.apply(
        root / ".fleet",
        config.default_files(
            "baseline-fixture",
            profile,
            sandbox_configuration=SandboxConfiguration(provider="docker", image="test:prepared"),
        ),
    )
    repository._run(["git", "add", "--", ".fleet"], cwd=root)
    repository._run(
        [
            "git",
            "commit",
            "--no-gpg-sign",
            "--no-verify",
            "--no-status",
            "-m",
            "fixture configuration",
        ],
        cwd=root,
    )
    container = build_baseline_container(tmp_path / "state", redactor=redactor)
    info = container.repository.inspect(root)
    now = container.state.clock.now()
    container.state.save_project(
        Project(
            project_id="prj_" + "1" * 32,
            canonical_root=info.root,
            identity_hash=info.identity_hash,
            created_at=now,
            updated_at=now,
        )
    )
    provider = container.sandboxes.get("docker")
    assert isinstance(provider, DockerSandboxProvider)
    runner = BaselineRecordingRunner(root, provider.git_shadow_path)
    provider.runner = runner
    provider.docker_executable = "/usr/bin/docker"
    provider.uid = provider.gid = 1000
    spec, snapshot = config.load_snapshot(root / ".fleet" / "fleet.yaml")
    command = next(iter(config.verification_profile(spec, snapshot).commands))
    return container, root, command, runner


def set_baseline_output(
    monkeypatch: pytest.MonkeyPatch,
    runner: BaselineRecordingRunner,
    *,
    stdout: bytes,
    stderr: bytes,
    returncode: int = 0,
    output_truncated: bool = False,
) -> None:
    original = runner.run
    runner.start_returncode = returncode

    async def controlled(
        argv: tuple[str, ...],
        *,
        environment: dict[str, str],
        cwd: str | None = None,
        timeout_seconds: int,
        max_output_bytes: int,
    ) -> ProcessResult:
        result = await original(
            argv,
            environment=environment,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        if argv[1:4] == ("container", "start", "--attach"):
            return ProcessResult(
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
                output_truncated=output_truncated,
            )
        return result

    monkeypatch.setattr(runner, "run", controlled)


@pytest.mark.asyncio
async def test_registered_model_free_baseline_observes_and_never_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("model-free composition constructed a model or secret dependency")

    for name in ("RuntimeRegistry", "EnvironmentSecretStore"):
        monkeypatch.setattr(bootstrap, name, forbidden)
    container, root, command, runner = business_fixture(tmp_path)
    before = container.repository.inspect(root)
    planned = await container.service.plan(root, command)
    assert planned.review.status == "ready"
    assert planned.observation is None
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)
    with pytest.raises(FleetError):
        await container.service.run(planned.review.review_id, allow_once=False, review_sha256=None)
    assert container.store.show(planned.review.review_id).execution.owner_claim_id is None
    completed = await container.service.run(
        planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
    )
    assert completed.report is not None, completed
    assert completed.report.status == "observed", completed.report
    assert completed.report.observed_exit_code == 0 and completed.report.cleanup_complete
    assert completed.report.target_applied is False
    assert completed.report.completion_assurance == "baseline_observation_only"
    observation = completed.observation
    assert observation is not None and observation.stdout == "verification passed\n"
    assert container.store.observation(planned.review.baseline_id) == observation
    assert observation.post_source_sha256 == planned.review.approved_source_sha256
    assert all(
        item.status == "released"
        for item in container.store.baseline_resource_snapshot(planned.review.baseline_id).leases
    )
    assert sum(argv[1:3] == ("container", "create") for argv, _ in runner.calls) == 1
    assert sum(argv[1:3] == ("container", "start") for argv, _ in runner.calls) == 1
    call_count = len(runner.calls)
    assert (
        await container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
        == completed
    )
    assert len(runner.calls) == call_count
    assert container.repository.inspect(root) == before
    with sqlite3.connect(container.state.database_path) as connection:
        for table in (
            "runs",
            "tasks",
            "agent_instances",
            "tool_intents",
            "resource_leases",
            "artifacts",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.parametrize("mode", ["nonzero", "timeout", "truncated", "redaction"])
async def test_observed_nonzero_is_distinct_from_unknown_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    if mode == "nonzero":
        runner.start_returncode = 1
    elif mode == "timeout":
        runner.start_timed_out = True
    elif mode == "truncated":
        runner.start_output_truncated = True
    else:
        set_baseline_output(
            monkeypatch,
            runner,
            stdout=b"\x1b" * 11_000,
            stderr=b"",
        )
    planned = await container.service.plan(root, command)
    result = await container.service.run(
        planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
    )
    assert result.report is not None and result.report.cleanup_complete
    observation = result.observation
    assert observation is not None
    assert container.store.observation(planned.review.baseline_id) == observation
    assert container.service.show(planned.review.baseline_id).observation == observation
    if mode == "nonzero":
        assert result.report.status == "observed" and observation.exit_code == 1
        assert baseline_exit_code(result) == 1
    elif mode == "redaction":
        assert result.report.status == "inconclusive" and observation.exit_code == 0
        assert observation.redaction_truncated
        assert len(observation.stdout.encode()) == 64_000
        assert "\x1b" not in observation.stdout
        assert baseline_exit_code(result) == 3
    else:
        assert result.report.status == "inconclusive" and observation.exit_code is None
        assert baseline_exit_code(result) == 3
    assert sum(argv[1:3] == ("container", "create") for argv, _ in runner.calls) == 1
    assert runner.listed_ids == []


async def test_public_observation_contains_only_persisted_safe_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "fixture-secret-value"
    container, root, command, runner = business_fixture(tmp_path, redactor=Redactor([secret]))
    set_baseline_output(
        monkeypatch,
        runner,
        stdout=f"before {secret} \x1b after\n".encode(),
        stderr=b"assertion failure \x00\n",
        returncode=1,
    )
    planned = await container.service.plan(root, command)
    result = await container.service.run(
        planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
    )
    observation = result.observation
    assert observation is not None
    assert observation.stdout == "before <redacted:1> \\u001b after\n"
    assert observation.stderr == "assertion failure \\u0000\n"
    assert observation.stdout_sha256 == sha256_bytes(observation.stdout.encode())
    assert observation.stderr_sha256 == sha256_bytes(observation.stderr.encode())
    assert secret not in result.model_dump_json()
    assert "\x1b" not in result.model_dump_json() and "\x00" not in result.model_dump_json()
    assert result.report is not None and result.report.status == "observed"
    assert baseline_exit_code(result) == 1


@pytest.mark.parametrize("mutation", ["tracked", "assume_unchanged", "revoked"])
async def test_stale_or_revoked_review_fails_before_claim(tmp_path: Path, mutation: str) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    planned = await container.service.plan(root, command)
    if mutation == "revoked":
        container.service.revoke(planned.review.review_id)
    else:
        if mutation == "assume_unchanged":
            container.repository._run(
                ["git", "update-index", "--assume-unchanged", "src/canary_calc/core.py"], cwd=root
            )
        (root / "src/canary_calc/core.py").write_text("changed after consent\n")
    with pytest.raises(FleetError):
        await container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
    assert container.store.show(planned.review.review_id).execution.owner_claim_id is None
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)


async def test_repeated_cancellation_joins_owned_cleanup_and_never_replays(tmp_path: Path) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    planned = await container.service.plan(root, command)
    runner.block_start = runner.block_rm = True
    task = asyncio.create_task(
        container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
    )
    try:
        await asyncio.wait_for(runner.start_entered.wait(), timeout=60)
        task.cancel()
        await asyncio.wait_for(runner.rm_entered.wait(), timeout=15)
        task.cancel()
        runner.rm_release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        shown = container.service.show(planned.review.baseline_id)
        assert shown.report is not None and shown.report.status == "inconclusive"
        assert shown.report.cleanup_complete and "controller_error" in shown.report.proof_gaps
        assert runner.listed_ids == []
        assert all(
            item.status == "released"
            for item in container.store.baseline_resource_snapshot(
                planned.review.baseline_id
            ).leases
        )
        count = len(runner.calls)
        assert (
            await container.service.run(
                planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
            )
            == shown
        )
        assert len(runner.calls) == count
    finally:
        runner.start_release.set()
        runner.rm_release.set()
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


@pytest.mark.parametrize("boundary", ["mark_creation", "record_native", "record_observation"])
async def test_creation_crash_windows_retain_exact_spent_owner_and_honest_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    planned = await container.service.plan(root, command)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("fixture failure must never enter durable evidence")

    method = {
        "mark_creation": "mark_baseline_creation_dispatched",
        "record_native": "activate_baseline_execution",
        "record_observation": "record_command_observation",
    }[boundary]
    with monkeypatch.context() as scoped:
        scoped.setattr(container.store, method, fail)
        shown = await container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
    assert shown.execution.owner_claim_id is not None
    snapshot = container.store.baseline_resource_snapshot(planned.review.baseline_id)
    assert snapshot.dispatch is not None and len(snapshot.leases) == 3
    assert container.store.observation(planned.review.baseline_id) is None
    assert shown.report is not None and "missing_result" in shown.report.proof_gaps
    assert "fixture failure" not in shown.model_dump_json()
    assert shown.report.cleanup_complete is (boundary != "record_native")
    assert shown.report.status == (
        "recovery_required" if boundary == "record_native" else "inconclusive"
    )
    assert sum(argv[1:3] == ("container", "start") for argv, _ in runner.calls) == (
        1 if boundary == "record_observation" else 0
    )
    count = len(runner.calls)
    assert (
        await container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
        == shown
    )
    assert len(runner.calls) == count
    if boundary == "record_native":
        # Unknown create + locally removed native cannot become a durable absence
        # proof. Parent workspace/sandbox leases deliberately remain retained.
        assert [item.kind for item in snapshot.leases if item.status == "failed"] == ["execution"]
        assert all(item.status == "active" for item in snapshot.leases if item.kind != "execution")
        assert runner.listed_ids == []


@pytest.mark.parametrize("mutation", ["extra", "mode", "bytes"])
async def test_actual_staging_must_match_approved_manifest_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    planned = await container.service.plan(root, command)
    original = container.repository.materialize_baseline_workspace

    def change_staging(source: Path, workspace: BaselineWorkspace) -> BaselineWorkspace:
        created = original(source, workspace)
        staging = Path(created.path)
        path = staging / "src/canary_calc/core.py"
        if mutation == "extra":
            (staging / "extra.py").write_text("unreviewed source\n")
        elif mutation == "mode":
            path.chmod(0o755)
        else:
            path.write_text("unreviewed replacement\n")
        return created

    with monkeypatch.context() as scoped:
        scoped.setattr(container.repository, "materialize_baseline_workspace", change_staging)
        shown = await container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
    assert shown.report is not None and shown.report.status == "inconclusive"
    assert shown.report.cleanup_complete and shown.report.observation is None
    assert container.store.baseline_resource_snapshot(planned.review.baseline_id).dispatch is None
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)
    assert container.repository.inspect(root).dirty_paths == []


@pytest.mark.parametrize("mixed", ["claim", "workspace", "sandbox"])
async def test_gateway_rejects_two_baseline_identity_substitution_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mixed: str,
) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    primary = await container.service.plan(root, command)
    other = await container.service.plan(root, command)
    authorization = container.store.authorize(other.review.review_id, other.review.digest)
    foreign = container.store.claim_baseline(
        other.review.review_id, other.review.digest, authorization.authorization_id, 0
    )
    original = container.gateway.execute_baseline

    async def substituted(
        *,
        claim: BaselineOwnerClaim,
        workspace: BaselineWorkspace,
        sandbox_handle: BaselineSandboxHandle,
    ) -> BaselineCommandObservation:
        if mixed == "claim":
            claim = foreign
        elif mixed == "workspace":
            workspace = workspace.model_copy(update={"owner": foreign.owner})
        else:
            sandbox_handle = sandbox_handle.model_copy(update={"owner": foreign.owner})
        return await original(claim=claim, workspace=workspace, sandbox_handle=sandbox_handle)

    with monkeypatch.context() as scoped:
        scoped.setattr(container.gateway, "execute_baseline", substituted)
        shown = await container.service.run(
            primary.review.review_id, allow_once=True, review_sha256=primary.review.digest
        )
    assert shown.report is not None and shown.report.status == "inconclusive"
    assert shown.report.cleanup_complete and shown.report.observation is None
    primary_snapshot = container.store.baseline_resource_snapshot(primary.review.baseline_id)
    other_snapshot = container.store.baseline_resource_snapshot(other.review.baseline_id)
    assert primary_snapshot.dispatch is other_snapshot.dispatch is None
    assert other_snapshot.leases == ()
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)
    # Fence the second synthetic controller claim; it allocated no physical resources.
    container.store.begin_baseline_cleanup(foreign, other_snapshot)


async def test_missing_current_baseline_capability_refuses_before_consent_and_workspace(
    tmp_path: Path,
) -> None:
    container, root, command, runner = business_fixture(tmp_path)
    planned = await container.service.plan(root, command)
    container.sandboxes._baseline_providers.clear()
    with pytest.raises(FleetError):
        await container.service.run(
            planned.review.review_id, allow_once=True, review_sha256=planned.review.digest
        )
    shown = container.store.show(planned.review.review_id)
    assert shown.execution.owner_claim_id is None and shown.report is None
    with sqlite3.connect(container.state.database_path) as connection:
        for table in (
            "baseline_authorizations",
            "baseline_owner_claims",
            "baseline_resource_leases",
            "baseline_dispatch_claims",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert not (Path(container.state.database_path).parent / "baseline-workspaces").exists()
    assert not any(argv[1:3] == ("container", "create") for argv, _ in runner.calls)
