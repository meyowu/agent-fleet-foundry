"""Read-only static inspection, deliberately independent of the execution container."""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.readiness import (
    MAX_READINESS_BYTES,
    MAX_READINESS_COMMANDS,
    MAX_READINESS_DIAGNOSTICS,
    DiagnosticCode,
    ReadinessBoundary,
    ReadinessCommand,
    ReadinessDiagnostic,
    ReadinessReport,
    StaticReadinessMetadata,
    static_path,
)
from agent_fleet.domain.repository_profile import CommandPurpose, Confidence
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.readiness import ReadinessProfilerPort
from agent_fleet.ports.repository import RepositoryPort

_TOKEN = re.compile(r"[A-Za-z0-9_./*?=+~-]{1,256}\Z")
_LOCK_NAMES = frozenset(
    {
        "uv.lock",
        "poetry.lock",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "Cargo.lock",
    }
)


def admission_error() -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        "Static repository inspection could not be admitted.",
        "Use fleet readiness --help and a readable, committed Git repository.",
    )


class ReadinessService:
    def __init__(
        self,
        repository: RepositoryPort,
        profiler: ReadinessProfilerPort,
        config: ConfigurationPort,
        redactor: Redactor,
    ) -> None:
        self.repository = repository
        self.profiler = profiler
        self.config = config
        self.redactor = redactor

    def inspect(self, path: Path) -> ReadinessReport:
        admitted = False
        try:
            info = self.repository.inspect(path)
            result, metadata = self.profiler.profile_with_metadata(Path(info.root))
            admitted = True
        except (FleetError, OSError, ValueError, subprocess.SubprocessError):
            pass
        if not admitted:
            raise admission_error()
        profile = result.profile
        diagnostics: list[ReadinessDiagnostic] = []
        omitted_diagnostics = 0

        def issue(code: DiagnosticCode) -> None:
            nonlocal omitted_diagnostics
            if len(diagnostics) < MAX_READINESS_DIAGNOSTICS:
                diagnostics.append(ReadinessDiagnostic(code=code))
            else:
                omitted_diagnostics += 1

        # A typed adapter result is still inspected before becoming public output.
        if self.redactor.contains_secret_data(metadata.model_dump(mode="json")):
            metadata = StaticReadinessMetadata(
                omitted_manifests=len(metadata.manifests) + metadata.omitted_manifests,
                omitted_declarations=len(metadata.declarations) + metadata.omitted_declarations,
                omitted_diagnostics=len(metadata.diagnostics) + metadata.omitted_diagnostics,
            )
            issue("unsafe_projection")
        for _ in profile.ambiguities:
            # Existing ambiguity messages include parser/input text; never forward them.
            issue("profile_incomplete")

        boundaries: list[ReadinessBoundary] = []
        omitted_boundaries = 0
        for item in profile.boundaries:
            if len(boundaries) >= 64:
                omitted_boundaries += 1
                issue("boundary_limit")
                continue
            try:
                boundary = ReadinessBoundary(path=item.path, ecosystems=tuple(item.ecosystems))
                if self.redactor.contains_secret_data(boundary.model_dump(mode="json")):
                    raise ValueError("unsafe projection")
                boundaries.append(boundary)
            except ValueError:
                omitted_boundaries += 1
                issue("unsafe_projection")

        locks: list[str] = []
        omitted_locks = 0
        for value in sorted(
            {signal.path for signal in profile.signals if Path(signal.path).name in _LOCK_NAMES}
        ):
            try:
                static_path(value)
                if ":" in value or "\\" in value or self.redactor.contains_secret(value):
                    raise ValueError("unsafe projection")
                if len(locks) >= 64:
                    raise ValueError("bounded projection")
                locks.append(value)
            except ValueError:
                omitted_locks += 1
                issue("unsafe_projection")

        configured: list[ReadinessCommand] = []
        candidates: list[ReadinessCommand] = []
        omitted_commands = 0
        configuration_status: Literal["absent", "valid", "invalid"] = "absent"
        config_hash: str | None = None
        config_path = Path(info.root) / ".fleet"
        if config_path.exists() or config_path.is_symlink():
            try:
                if config_path.is_symlink() or not config_path.is_dir():
                    raise ValueError("unsafe configuration boundary")
                spec, snapshot = self.config.load_snapshot(config_path / "fleet.yaml")
                verification = self.config.verification_profile(spec, snapshot)
                config_hash = self.config.snapshot_hash(snapshot)
                configuration_status = "valid"
                for name, command in sorted(verification.commands.items()):
                    try:
                        configured.append(
                            self._command(
                                name=name,
                                purpose="check",
                                executable=command.executable,
                                argv=tuple(command.argv),
                                cwd=command.cwd,
                                provenance=spec.spec.project.verification,
                                required=name in verification.required_for_code_change,
                            )
                        )
                    except ValueError:
                        omitted_commands += 1
                        issue("unsafe_projection")
            except (FleetError, OSError, ValueError, TypeError, RecursionError):
                configuration_status = "invalid"
                config_hash = None
                configured = []
                issue("configuration_invalid")

        for candidate in profile.commands:
            if len(configured) + len(candidates) >= MAX_READINESS_COMMANDS:
                omitted_commands += 1
                issue("command_limit")
                continue
            try:
                candidates.append(
                    self._command(
                        name=candidate.name,
                        purpose=candidate.purpose,
                        executable=candidate.executable,
                        argv=tuple(candidate.argv),
                        cwd=candidate.cwd,
                        provenance=candidate.provenance.path,
                        confidence=candidate.confidence,
                    )
                )
            except ValueError:
                omitted_commands += 1
                issue("unsafe_projection")
        available = configured if configuration_status == "valid" else candidates
        if not any(command.purpose != "other" for command in available):
            issue("verification_commands_missing")

        # One aggregate diagnostic budget, including metadata diagnostics.
        metadata_data = metadata.model_dump(mode="python")
        room = MAX_READINESS_DIAGNOSTICS - len(diagnostics)
        omitted_diagnostics += max(0, len(metadata.diagnostics) - room)
        metadata_data["diagnostics"] = metadata.diagnostics[:room]
        metadata = StaticReadinessMetadata.model_validate(metadata_data)
        data = {
            "repository_identity": info.identity_hash,
            "head_revision": info.head_revision,
            "status_fingerprint": info.status_fingerprint,
            "dirty": bool(info.dirty_paths),
            "profile_sha256": canonical_json_hash(profile.model_dump(mode="json")),
            "configuration_status": configuration_status,
            "config_snapshot_sha256": config_hash,
            "ecosystems": tuple(profile.ecosystems),
            "boundaries": tuple(boundaries),
            "lock_files": tuple(locks),
            "metadata": metadata,
            "detected_candidates": tuple(candidates),
            "configured_commands": tuple(configured),
            "diagnostics": tuple(diagnostics),
            "omitted_commands": omitted_commands,
            "omitted_boundaries": omitted_boundaries,
            "omitted_diagnostics": omitted_diagnostics,
            "omitted_lock_files": omitted_locks,
        }
        return self._bounded_report(data)

    def _command(
        self,
        *,
        name: str,
        purpose: CommandPurpose,
        executable: str,
        argv: tuple[str, ...],
        cwd: str,
        provenance: str | None,
        confidence: Confidence | None = None,
        required: bool = False,
    ) -> ReadinessCommand:
        raw = {
            "name": name,
            "purpose": purpose,
            "executable": executable,
            "argv": argv,
            "cwd": cwd,
            "provenance_path": provenance,
            "confidence": confidence,
            "profile_required": required,
        }
        if (
            any(_TOKEN.fullmatch(value) is None for value in (name, executable, *argv))
            or executable in {"sh", "bash", "zsh", "fish", "cmd", "powershell", "pwsh"}
            or any(value in {"-c", "-e", "--eval", "--command"} for value in argv)
            or self.redactor.contains_secret_data(raw)
        ):
            raise ValueError("command is not safe for static projection")
        return ReadinessCommand(**raw, sha256=canonical_json_hash(raw))  # type: ignore[arg-type]

    @staticmethod
    def _bounded_report(
        data: dict[str, object], *, wire_size: Callable[[dict[str, object]], int] | None = None
    ) -> ReadinessReport:
        # Project into primitive JSON to enforce the wire budget before validation.
        primitive = json.loads(
            json.dumps(data, default=lambda value: value.model_dump(mode="json"))
        )
        primitive.update(
            api_version="agentfleet.dev/v1alpha1",
            kind="ReadinessReport",
            environment_status="unverified",
            baseline_status="not_checked",
            execution_authorized=False,
            commands_executed=0,
        )
        measure = wire_size or (
            lambda value: len(json.dumps(value, ensure_ascii=True).encode("utf-8"))
        )
        removable = (
            (primitive, "detected_candidates", "omitted_commands"),
            (primitive["metadata"], "declarations", "omitted_declarations"),
            (primitive, "configured_commands", "omitted_commands"),
            (primitive["metadata"], "manifests", "omitted_manifests"),
            (primitive, "boundaries", "omitted_boundaries"),
            (primitive, "lock_files", "omitted_lock_files"),
            (primitive["metadata"], "diagnostics", "omitted_diagnostics"),
            (primitive, "diagnostics", "omitted_diagnostics"),
        )
        truncated = False
        while True:
            incomplete = bool(
                primitive["diagnostics"]
                or primitive["metadata"]["diagnostics"]
                or any(
                    primitive[key]
                    for key in (
                        "omitted_commands",
                        "omitted_boundaries",
                        "omitted_diagnostics",
                        "omitted_lock_files",
                    )
                )
                or any(
                    primitive["metadata"][key]
                    for key in (
                        "omitted_manifests",
                        "omitted_declarations",
                        "omitted_diagnostics",
                    )
                )
            )
            primitive["inspection_complete"] = not incomplete
            primitive["next_steps"] = (["review_static_issues"] if incomplete else []) + [
                "prepare_reviewed_environment",
                "run_approved_baseline_later",
            ]
            if measure(primitive) <= MAX_READINESS_BYTES:
                break
            if not truncated:
                count = len(primitive["diagnostics"]) + len(primitive["metadata"]["diagnostics"])
                if count < MAX_READINESS_DIAGNOSTICS:
                    primitive["diagnostics"].append({"code": "report_byte_limit", "path": None})
                else:
                    primitive["omitted_diagnostics"] += 1
                truncated = True
            for container, field, counter in removable:
                if container[field]:
                    container[field].pop()
                    container[counter] += 1
                    break
            else:  # Fixed scalar fields are below the wire limit by construction.
                raise admission_error()
        report: ReadinessReport | None = None
        with suppress(ValidationError):
            report = ReadinessReport.model_validate_json(json.dumps(primitive))
        if report is None:
            raise admission_error()
        return report
