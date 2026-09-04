"""Repository facts discovered without executing repository-controlled code."""

from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, Field

from agent_fleet.domain.models import Sha256, StrictModel

Ecosystem = Literal[
    "python",
    "node",
    "go",
    "rust",
    "maven",
    "gradle",
    "make",
    "github-actions",
]
Confidence = Literal["high", "medium", "low"]
CommandPurpose = Literal["test", "lint", "build", "check", "other"]


class CommandProvenance(StrictModel):
    path: str
    source: str
    pointer: str | None = None


class RepositoryCommand(StrictModel):
    """An untrusted command candidate; detection is never authorization."""

    name: str
    purpose: CommandPurpose
    executable: str
    argv: list[str]
    cwd: str
    provenance: CommandProvenance
    confidence: Confidence
    execution_authorized: Literal[False] = False


class RepositorySignal(StrictModel):
    ecosystem: Ecosystem
    path: str
    signal: str


class RepositoryBoundary(StrictModel):
    path: str
    ecosystems: list[Ecosystem]
    manifests: list[str]


class RepositoryAmbiguity(StrictModel):
    code: str
    message: str
    paths: list[str] = Field(default_factory=list)


class RepositoryProfile(StrictModel):
    schema_version: Literal[1] = 1
    root: Literal["."] = "."
    ecosystems: list[Ecosystem]
    build_systems: list[str]
    boundaries: list[RepositoryBoundary]
    signals: list[RepositorySignal]
    commands: list[RepositoryCommand]
    ambiguities: list[RepositoryAmbiguity]
    files_read: list[str]
    bytes_read: int = Field(ge=0, le=512_000)


class ProjectKnowledge(StrictModel):
    """Portable project facts derived entirely from a RepositoryProfile."""

    schema_version: Literal[1] = 1
    source_profile_sha256: Sha256 = Field(
        validation_alias=AliasChoices("source_profile_sha256", "knowledge_hash")
    )
    summary: str
    ecosystems: list[Ecosystem]
    build_systems: list[str]
    repository_boundaries: list[str]
    verification_commands: list[str]
    ambiguities: list[str]


class RepositoryProfileResult(StrictModel):
    profile: RepositoryProfile
    project_knowledge: ProjectKnowledge
