"""Offline-testable evidence retention for one explicitly opted-in disposable canary."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sqlite3
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Self
from urllib.parse import quote, quote_plus

from pydantic import BaseModel, ConfigDict, StrictInt, model_validator

from agent_fleet.adapters.config.yaml import YamlConfigurationAdapter
from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import ApplicationContainer, build_container
from agent_fleet.domain.errors import FleetError
from agent_fleet.domain.model_profiles import validate_profile_configuration
from agent_fleet.domain.models import RunStatus, RuntimeConfiguration
from agent_fleet.domain.security import canonical_json_hash
from agent_fleet.domain.workflow import is_terminal
from agent_fleet.ports.secret_store import SecretRef

EVIDENCE_DIRECTORY_ENV = "AGENT_FLEET_LIVE_EVIDENCE_DIR"
SELECTION_ENV = "AGENT_FLEET_LIVE_SELECTION_JSON"
SELECTION_ROLES = ("cos", "engineer", "verifier")
ROOT_LIMITS = {
    "max_agent_invocations": 12,
    "max_model_requests": 24,
    "max_tool_calls": 32,
    "max_total_tokens": 65_536,
    "max_active_seconds": 600,
}
PROFILE_LIMITS = {
    "max_requests": 8,
    "max_tool_calls": 12,
    "max_total_tokens": 32_768,
    "timeout_seconds": 120,
    "max_retries": 1,
}

_DEDICATED_CREDENTIAL_ENV = re.compile(r"FLEET_[A-Z][A-Z0-9_]*\Z")


class LiveCanaryRoleSelection(BaseModel):
    """Exact public model-profile inputs for one required canary role."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    runtime_name: str
    provider_model: str
    credential_ref: str

    @model_validator(mode="after")
    def validate_existing_configuration_admission(self) -> Self:
        configuration = RuntimeConfiguration(
            runtime_name=self.runtime_name,
            provider_model=self.provider_model,
            credential_ref=self.credential_ref,
            **PROFILE_LIMITS,
        )
        validate_profile_configuration(configuration)
        name = SecretRef.parse(self.credential_ref).name
        if _DEDICATED_CREDENTIAL_ENV.fullmatch(name) is None:
            raise ValueError("selected credential must use a dedicated FLEET_ variable")
        return self

    def configuration(self) -> RuntimeConfiguration:
        return RuntimeConfiguration(
            runtime_name=self.runtime_name,
            provider_model=self.provider_model,
            credential_ref=self.credential_ref,
            **PROFILE_LIMITS,
        )

    @property
    def provider_family(self) -> str:
        provider = self.provider_model.partition(":")[0]
        return "openai" if provider in {"openai", "openai-chat"} else provider


class LiveCanarySelection(BaseModel):
    """Strict, finite selection for exactly the three live canary roles."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: StrictInt
    cos: LiveCanaryRoleSelection
    engineer: LiveCanaryRoleSelection
    verifier: LiveCanaryRoleSelection

    @model_validator(mode="after")
    def reject_cross_provider_shared_reference(self) -> Self:
        if self.schema_version != 1:
            raise ValueError("live canary selection schema version is unsupported")
        roles = self.roles
        for index, left_name in enumerate(SELECTION_ROLES):
            left = roles[left_name]
            for right_name in SELECTION_ROLES[index + 1 :]:
                right = roles[right_name]
                if (
                    left.provider_family != right.provider_family
                    and left.credential_ref == right.credential_ref
                ):
                    raise ValueError("cross-provider credential isolation failed")
        return self

    @property
    def roles(self) -> dict[str, LiveCanaryRoleSelection]:
        return {name: getattr(self, name) for name in SELECTION_ROLES}

    @property
    def canonical_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    def safe_projection(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "roles": {
                role: {
                    "runtime_name": selected.runtime_name,
                    "provider_model": selected.provider_model,
                }
                for role, selected in self.roles.items()
            },
        }


def default_live_canary_selection() -> LiveCanarySelection:
    role = {
        "runtime_name": "pydantic-ai",
        "provider_model": "openai:gpt-5-nano",
        "credential_ref": "env:FLEET_OPENAI_TEST_KEY",
    }
    return LiveCanarySelection.model_validate(
        {"schema_version": 1, **{name: dict(role) for name in SELECTION_ROLES}}
    )


def parse_live_canary_selection(payload: bytes | str) -> LiveCanarySelection:
    """Parse one bounded JSON object, rejecting duplicate keys and non-canonical shapes."""
    encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
    if not encoded or len(encoded) > 16 * 1024:
        raise ValueError("live canary selection exceeds its bounded JSON size")

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("live canary selection contains a duplicate field")
            result[name] = value
        return result

    try:
        value = json.loads(encoded, object_pairs_hook=unique_object)
    except (TypeError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("live canary selection is invalid JSON") from error
    return LiveCanarySelection.model_validate(value)


def resolve_live_canary_credentials(
    selection: LiveCanarySelection,
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Resolve only explicitly selected references and enforce provider-family isolation."""
    resolved: dict[str, str] = {}
    role_values: dict[str, str] = {}
    for role, selected in selection.roles.items():
        name = SecretRef.parse(selected.credential_ref).name
        value = environment.get(name, "")
        try:
            encoded = value.encode("ascii")
        except UnicodeEncodeError:
            encoded = b""
        if not 16 <= len(encoded) <= 16_384 or any(byte < 0x21 or byte > 0x7E for byte in encoded):
            raise ValueError("selected credential is not ready")
        resolved[name] = value
        role_values[role] = value
    for index, left_name in enumerate(SELECTION_ROLES):
        left = selection.roles[left_name]
        for right_name in SELECTION_ROLES[index + 1 :]:
            right = selection.roles[right_name]
            if (
                left.provider_family != right.provider_family
                and role_values[left_name] == role_values[right_name]
            ):
                raise ValueError("cross-provider credential isolation failed")
    return resolved


def selected_credential_forms(credentials: Mapping[str, str]) -> tuple[bytes, ...]:
    return tuple(
        sorted(
            {form for value in credentials.values() for form in credential_forms(value)},
            key=len,
            reverse=True,
        )
    )


def prepare_live_canary_fixture(destination: Path) -> Path:
    """Prepare a new module-repair fixture, not a synthetic package-build claim."""
    if destination.exists() or destination.is_symlink():
        raise ValueError("live canary fixture requires a new disposable destination")
    repository = GitRepositoryAdapter(destination.parent, UuidIdGenerator())
    target = repository.create_canary_fixture(destination)
    manifest = resources.files("agent_fleet").joinpath("assets/canary/pyproject.toml")
    (target / "pyproject.toml").write_text(manifest.read_text(encoding="utf-8"), encoding="utf-8")
    profile = StaticRepositoryProfiler().profile(target).profile
    assert [
        (command.name, command.executable, command.argv, command.purpose)
        for command in profile.commands
    ] == [("python-test", "python", ["-m", "pytest"], "test")]
    repository._run(["git", "add", "--", "pyproject.toml"], cwd=target)
    repository._run(
        ["git", "commit", "--no-gpg-sign", "--no-verify", "-m", "Declare standalone canary tests"],
        cwd=target,
    )
    return target


def assert_live_canary_verification(repository: Path) -> None:
    """Check the actual admitted configuration, without weakening completion policy."""
    config = YamlConfigurationAdapter()
    spec, snapshot = config.load_snapshot(repository / ".fleet/fleet.yaml")
    verification = config.verification_profile(spec, snapshot)
    assert set(verification.commands) == {"python-test"}
    command = verification.commands["python-test"]
    assert command.executable == "python" and command.argv == ["-m", "pytest"]
    assert command.network_required is False
    assert config.required_verification_commands(
        spec,
        snapshot,
        workflow_id="code-change",
        allowed_paths=("src/canary_calc/core.py",),
        change_kind="code_change",
    ) == ("python-test",)


def credential_forms(secret: str) -> tuple[bytes, ...]:
    encoded = secret.encode("utf-8")
    standard_base64 = base64.b64encode(encoded).decode("ascii")
    urlsafe_base64 = base64.urlsafe_b64encode(encoded).decode("ascii")
    text_forms = {
        secret,
        quote(secret, safe=""),
        quote_plus(secret, safe=""),
        standard_base64,
        standard_base64.rstrip("="),
        urlsafe_base64,
        urlsafe_base64.rstrip("="),
        encoded.hex(),
        json.dumps(secret, ensure_ascii=True)[1:-1],
    }
    return tuple(
        sorted({item.encode("utf-8") for item in text_forms if item}, key=len, reverse=True)
    )


def require_secret_free(payload: bytes, forms: tuple[bytes, ...]) -> None:
    if any(form and form in payload for form in forms):
        raise RuntimeError("canary evidence contains a registered credential form")


def inspect_secret_free_tree(root: Path, forms: tuple[bytes, ...]) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            require_secret_free(path.read_bytes(), forms)


def write_safe_json(directory: Path, name: str, value: object, forms: tuple[bytes, ...]) -> None:
    """Write only private, exclusive evidence files after validating their full bytes."""
    if name not in {"canary-evidence.json", "cleanup.json"}:
        raise ValueError("unsupported canary evidence filename")
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("canary evidence exceeds its export limit")
    require_secret_free(payload, forms)
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("canary evidence directory must be user-owned and private")
        target = os.open(
            name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=descriptor
        )
        with os.fdopen(target, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _run_ids(container: ApplicationContainer) -> tuple[str, ...]:
    # The public StateStore deliberately has no unbounded list_runs operation. This
    # test-only read discovers IDs only inside this one new disposable installation.
    uri = container.state.database_path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute("SELECT run_id FROM runs ORDER BY run_id").fetchall()
    return tuple(container.state.get_run(row[0]).run_id for row in rows)


def _error_code(error: Exception) -> str:
    return error.code.value if isinstance(error, FleetError) else "CANARY_OBSERVATION_FAILED"


def _root_run_id(container: ApplicationContainer, run_id: str) -> str:
    seen: set[str] = set()
    while run_id not in seen:
        seen.add(run_id)
        binding = container.graphs.child_binding(run_id)
        if binding is None:
            return run_id
        run_id = binding.parent_run_id
    raise RuntimeError("disposable canary graph contains a parent cycle")


def cleanup_disposable_state(state_root: Path, *, owner_stopped: bool) -> dict[str, object]:
    """Clean exact persisted owners, never replaying a stopped model invocation.

    Caller must supply a newly-created disposable Fleet root, after its synchronous
    CLI owner or entire launcher child process has exited. Never use a user Fleet root.
    """
    if not owner_stopped:
        raise ValueError("canary cleanup requires a stopped execution owner")
    actions: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    outstanding: list[dict[str, object]] = []
    if not (state_root / "state.db").exists():
        return {"complete": True, "actions": actions, "errors": errors, "outstanding_leases": []}
    try:
        container = build_container(state_root)
        roots = sorted({_root_run_id(container, run_id) for run_id in _run_ids(container)})
        for run_id in roots:
            run = container.state.get_run(run_id)
            owned_ids = container.recovery.owned_run_ids(run_id)
            leases = any(container.state.outstanding_leases(item) for item in owned_ids)
            action = "none"
            try:
                if run.status in {RunStatus.RUNNING, RunStatus.APPLYING} or (
                    is_terminal(run.status) and leases
                ):
                    action = "recover"
                    asyncio.run(container.recovery.recover_run(run_id))
                elif not is_terminal(run.status) and not (
                    run.status is RunStatus.READY_FOR_REVIEW and not leases
                ):
                    action = "cancel"
                    asyncio.run(container.cancellation.cancel(run_id))
            except Exception as error:
                errors.append({"run_id": run_id, "code": _error_code(error)})
            actions.append(
                {
                    "run_id": run_id,
                    "original_status": run.status.value,
                    "action": action,
                    "status_after_cleanup": container.state.get_run(run_id).status.value,
                }
            )
        outstanding = [
            {"lease_id": item.lease_id, "run_id": item.run_id, "kind": item.kind.value}
            for item in container.state.outstanding_leases()
        ]
    except Exception as error:
        errors.append({"code": _error_code(error)})
    return {
        "complete": not errors and not outstanding,
        "actions": actions,
        "errors": errors,
        "outstanding_leases": outstanding,
    }


def capture_disposable_evidence(state_root: Path) -> dict[str, object]:
    """Capture pre-cleanup status and original artifacts, not post-cancel conclusions."""
    runs: list[dict[str, object]] = []
    errors: list[dict[str, str]] = []
    if not (state_root / "state.db").exists():
        return {"runs": runs, "errors": errors}
    try:
        container = build_container(state_root)
        for run_id in _run_ids(container):
            # Retain useful independent pieces if one integrity check fails.
            captured: dict[str, object] = {"run_id": run_id}
            for label, operation in (
                ("status", lambda identity=run_id: container.inspection.status(identity)),
                ("logs", lambda identity=run_id: container.inspection.logs(identity)),
                (
                    "artifacts",
                    lambda identity=run_id: container.inspection.artifacts_for_run(identity),
                ),
                (
                    "artifact_contents",
                    lambda identity=run_id: {
                        item.artifact_id: container.artifacts.read_text(item.artifact_id)
                        for item in container.state.list_artifacts(identity)
                    },
                ),
            ):
                try:
                    captured[label] = operation()
                except Exception as error:
                    errors.append({"run_id": run_id, "section": label, "code": _error_code(error)})
            runs.append(captured)
    except Exception as error:
        errors.append({"code": _error_code(error)})
    return {"runs": runs, "errors": errors}


@dataclass
class CanaryEvidence:
    state_root: Path
    repository: Path
    forms: tuple[bytes, ...]
    directory: Path | None = None
    selected_model: str = ""
    selection_sha256: str = ""
    selected_roles: dict[str, object] = field(default_factory=dict)
    cli_observations: list[dict[str, object]] = field(default_factory=list)
    passed: bool = False
    finalized: bool = False

    def finish(self) -> None:
        if self.finalized:
            return
        self.finalized = True
        original = capture_disposable_evidence(self.state_root)
        original.update(
            {
                "assertions_passed": self.passed,
                "selected_model": self.selected_model,
                "selection_sha256": self.selection_sha256,
                "selected_roles": self.selected_roles,
                "root_limits": ROOT_LIMITS,
                "profile_limits": PROFILE_LIMITS,
                "cli_observations": self.cli_observations,
            }
        )
        cleanup = cleanup_disposable_state(self.state_root, owner_stopped=True)
        # Scan even failed runs, but never let a leak prevent exact resource cleanup.
        scan_failed = False
        try:
            inspect_secret_free_tree(self.repository, self.forms)
            inspect_secret_free_tree(self.state_root, self.forms)
            require_secret_free(json.dumps(original).encode("utf-8"), self.forms)
        except Exception:
            scan_failed = True
            original = {"assertions_passed": False, "error": "CANARY_SECRET_SCAN_FAILED"}
        if self.directory is not None:
            write_safe_json(self.directory, "canary-evidence.json", original, self.forms)
            write_safe_json(self.directory, "cleanup.json", cleanup, self.forms)
        if scan_failed or original.get("errors") or not cleanup["complete"]:
            raise RuntimeError("canary teardown failed; inspect separate safe evidence and cleanup")
