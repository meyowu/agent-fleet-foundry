"""Static, containment-safe repository profiler.

The adapter reads only a bounded set of known metadata files.  It never invokes
Git, package managers, build tools, hooks, project scripts, or project code.
"""

from __future__ import annotations

import json
import os
import re
import stat
import tomllib
import xml.etree.ElementTree as ElementTree
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from yaml.tokens import AliasToken, AnchorToken

from agent_fleet.domain.repository_profile import (
    CommandProvenance,
    Ecosystem,
    ProjectKnowledge,
    RepositoryAmbiguity,
    RepositoryBoundary,
    RepositoryCommand,
    RepositoryProfile,
    RepositoryProfileResult,
    RepositorySignal,
)
from agent_fleet.domain.security import canonical_json_hash

MAX_PROFILE_READ_BYTES = 512_000
MAX_DISCOVERY_ENTRIES = 20_000
MAX_DISCOVERY_DEPTH = 12
MAX_NODE_SCRIPTS = 256

_SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".fleet",
        ".hg",
        ".svn",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "target",
        "vendor",
    }
)
_KNOWN_FILES = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "poetry.lock",
        "package.json",
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "bun.lock",
        "bun.lockb",
        "go.mod",
        "Cargo.toml",
        "Cargo.lock",
        "pom.xml",
        "mvnw",
        "build.gradle",
        "build.gradle.kts",
        "settings.gradle",
        "settings.gradle.kts",
        "gradlew",
        "Makefile",
        "makefile",
        "GNUmakefile",
    }
)
_MANIFEST_ECOSYSTEM: dict[str, Ecosystem] = {
    "pyproject.toml": "python",
    "package.json": "node",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "settings.gradle": "gradle",
    "settings.gradle.kts": "gradle",
    "Makefile": "make",
    "makefile": "make",
    "GNUmakefile": "make",
}
_LOCKFILE_MANAGERS = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lock": "bun",
    "bun.lockb": "bun",
}


@dataclass(frozen=True)
class _Candidate:
    path: Path
    relative: str


class _ReadBudget:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.remaining = MAX_PROFILE_READ_BYTES
        self.files_read: list[str] = []
        self.bytes_read = 0

    def read(self, candidate: _Candidate) -> bytes:
        """Read one regular non-symlink file without exceeding the global budget."""

        resolved = candidate.path.resolve(strict=True)
        resolved.relative_to(self.root)
        file_stat = candidate.path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise ValueError("not a regular non-symlink file")
        if file_stat.st_size > self.remaining:
            raise OverflowError("repository profile read budget exceeded")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(candidate.path, flags)
        try:
            opened_stat = os.fstat(descriptor)
            if not stat.S_ISREG(opened_stat.st_mode):
                raise ValueError("not a regular file")
            content = os.read(descriptor, self.remaining + 1)
        finally:
            os.close(descriptor)
        if len(content) > self.remaining:
            raise OverflowError("repository profile read budget exceeded")
        self.remaining -= len(content)
        self.bytes_read += len(content)
        self.files_read.append(candidate.relative)
        return content


class StaticRepositoryProfiler:
    """Discover repository metadata through bounded static inspection only."""

    def profile(self, root: Path) -> RepositoryProfileResult:
        canonical_root = root.resolve(strict=True)
        if not canonical_root.is_dir():
            raise ValueError(f"repository root is not a directory: {root}")

        ambiguities: list[RepositoryAmbiguity] = []
        candidates = self._discover(canonical_root, ambiguities)
        budget = _ReadBudget(canonical_root)
        by_name: dict[tuple[str, str], _Candidate] = {
            (self._boundary_for(item.relative), item.path.name): item for item in candidates
        }
        signals: list[RepositorySignal] = []
        commands: list[RepositoryCommand] = []
        build_systems: set[str] = set()
        boundary_ecosystems: dict[str, set[Ecosystem]] = defaultdict(set)
        boundary_manifests: dict[str, set[str]] = defaultdict(set)

        for candidate in candidates:
            name = candidate.path.name
            boundary = self._boundary_for(candidate.relative)
            ecosystem = self._ecosystem_for(candidate.relative, name)
            if ecosystem is not None:
                signals.append(
                    RepositorySignal(ecosystem=ecosystem, path=candidate.relative, signal=name)
                )
                boundary_ecosystems[boundary].add(ecosystem)
                if name in _MANIFEST_ECOSYSTEM or ecosystem == "github-actions":
                    boundary_manifests[boundary].add(candidate.relative)

        grouped_names: dict[str, set[str]] = defaultdict(set)
        for boundary, name in by_name:
            grouped_names[boundary].add(name)
        for boundary, names in sorted(grouped_names.items()):
            self._record_lockfile_ambiguities(boundary, names, ambiguities)

        for candidate in candidates:
            name = candidate.path.name
            boundary = self._boundary_for(candidate.relative)
            if name in {
                "uv.lock",
                "poetry.lock",
                "package-lock.json",
                "npm-shrinkwrap.json",
                "pnpm-lock.yaml",
                "yarn.lock",
                "bun.lock",
                "bun.lockb",
                "Cargo.lock",
                "mvnw",
                "gradlew",
            }:
                continue
            try:
                content = budget.read(candidate)
                text = content.decode("utf-8")
            except (OSError, UnicodeDecodeError, ValueError) as error:
                ambiguities.append(
                    self._ambiguity(
                        "manifest_unreadable",
                        f"Could not safely read {candidate.relative}: {error}",
                        [candidate.relative],
                    )
                )
                continue
            except OverflowError:
                ambiguities.append(
                    self._ambiguity(
                        "read_budget_exceeded",
                        f"Skipped {candidate.relative}; static profile reads are limited to "
                        f"{MAX_PROFILE_READ_BYTES} bytes in total.",
                        [candidate.relative],
                    )
                )
                continue

            try:
                if name == "pyproject.toml":
                    systems, discovered = self._python(candidate, text, grouped_names[boundary])
                elif name == "package.json":
                    systems, discovered = self._node(candidate, text, grouped_names[boundary])
                elif name == "go.mod":
                    systems, discovered = self._go(candidate, text)
                elif name == "Cargo.toml":
                    systems, discovered = self._rust(candidate, text)
                elif name == "pom.xml":
                    systems, discovered = self._maven(candidate, text, grouped_names[boundary])
                elif name in {"build.gradle", "build.gradle.kts"}:
                    systems, discovered = self._gradle(candidate, grouped_names[boundary])
                elif name in {"settings.gradle", "settings.gradle.kts"}:
                    systems, discovered = {"gradle"}, []
                elif name in {"Makefile", "makefile", "GNUmakefile"}:
                    systems, discovered = self._make(candidate, text)
                elif self._is_workflow(candidate.relative):
                    self._validate_workflow(text)
                    systems, discovered = {"github-actions"}, []
                else:
                    systems, discovered = set(), []
                build_systems.update(systems)
                commands.extend(discovered)
            except (json.JSONDecodeError, tomllib.TOMLDecodeError, ElementTree.ParseError) as error:
                ambiguities.append(
                    self._ambiguity(
                        "manifest_parse_failed",
                        f"Could not parse {candidate.relative}: {error}",
                        [candidate.relative],
                    )
                )
            except (RecursionError, TypeError, ValueError, yaml.YAMLError) as error:
                ambiguities.append(
                    self._ambiguity(
                        "manifest_parse_failed",
                        f"Could not parse {candidate.relative}: {error}",
                        [candidate.relative],
                    )
                )

        profile = RepositoryProfile(
            ecosystems=sorted({signal.ecosystem for signal in signals}),
            build_systems=sorted(build_systems),
            boundaries=[
                RepositoryBoundary(
                    path=path,
                    ecosystems=sorted(boundary_ecosystems[path]),
                    manifests=sorted(boundary_manifests[path]),
                )
                for path in sorted(boundary_ecosystems)
            ],
            signals=sorted(signals, key=lambda item: (item.path, item.ecosystem, item.signal)),
            commands=self._deduplicate_commands(commands),
            ambiguities=sorted(ambiguities, key=lambda item: (item.code, item.paths, item.message)),
            files_read=sorted(budget.files_read),
            bytes_read=budget.bytes_read,
        )
        profile_hash = canonical_json_hash(profile.model_dump(mode="json"))
        command_lines = [
            " ".join([command.executable, *command.argv])
            for command in profile.commands
            if command.purpose != "other"
        ]
        knowledge = ProjectKnowledge(
            source_profile_sha256=profile_hash,
            summary=self._summary(profile),
            ecosystems=profile.ecosystems,
            build_systems=profile.build_systems,
            repository_boundaries=[boundary.path for boundary in profile.boundaries],
            verification_commands=command_lines,
            ambiguities=[item.message for item in profile.ambiguities],
        )
        return RepositoryProfileResult(profile=profile, project_knowledge=knowledge)

    def _discover(self, root: Path, ambiguities: list[RepositoryAmbiguity]) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        pending = [root]
        entries_seen = 0
        while pending:
            directory = pending.pop()
            relative_directory = directory.relative_to(root)
            if len(relative_directory.parts) > MAX_DISCOVERY_DEPTH:
                ambiguities.append(
                    self._ambiguity(
                        "discovery_depth_exceeded",
                        f"Skipped directory deeper than {MAX_DISCOVERY_DEPTH}: "
                        f"{relative_directory.as_posix()}",
                        [relative_directory.as_posix()],
                    )
                )
                continue
            try:
                entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
            except OSError as error:
                relative = self._relative(root, directory)
                ambiguities.append(
                    self._ambiguity(
                        "directory_unreadable",
                        f"Could not inspect {relative}: {error}",
                        [relative],
                    )
                )
                continue
            for entry in entries:
                entries_seen += 1
                if entries_seen > MAX_DISCOVERY_ENTRIES:
                    ambiguities.append(
                        self._ambiguity(
                            "discovery_entry_limit_exceeded",
                            f"Stopped after {MAX_DISCOVERY_ENTRIES} repository entries.",
                        )
                    )
                    return sorted(candidates, key=lambda item: item.relative)
                entry_path = Path(entry.path)
                relative = self._relative(root, entry_path)
                interesting = entry.name in _KNOWN_FILES or self._is_workflow(relative)
                if entry.is_symlink():
                    if interesting:
                        ambiguities.append(
                            self._ambiguity(
                                "symlink_ignored",
                                f"Ignored symlinked repository metadata: {relative}",
                                [relative],
                            )
                        )
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in _SKIP_DIRECTORIES:
                        pending.append(entry_path)
                    continue
                if interesting and entry.is_file(follow_symlinks=False):
                    candidates.append(_Candidate(path=entry_path, relative=relative))
        return sorted(candidates, key=lambda item: item.relative)

    @staticmethod
    def _relative(root: Path, path: Path) -> str:
        resolved_parent = path.parent.resolve(strict=True)
        resolved_parent.relative_to(root)
        return path.relative_to(root).as_posix()

    @staticmethod
    def _is_workflow(relative: str) -> bool:
        parts = PurePosixPath(relative).parts
        return (
            len(parts) >= 3
            and parts[-3:-1] == (".github", "workflows")
            and parts[-1].lower().endswith((".yml", ".yaml"))
        )

    @classmethod
    def _boundary_for(cls, relative: str) -> str:
        path = PurePosixPath(relative)
        boundary_parts = path.parts[:-3] if cls._is_workflow(relative) else path.parts[:-1]
        return PurePosixPath(*boundary_parts).as_posix() if boundary_parts else "."

    @classmethod
    def _ecosystem_for(cls, relative: str, name: str) -> Ecosystem | None:
        if cls._is_workflow(relative):
            return "github-actions"
        if name in _MANIFEST_ECOSYSTEM:
            return _MANIFEST_ECOSYSTEM[name]
        if name in {"uv.lock", "poetry.lock"}:
            return "python"
        if name in _LOCKFILE_MANAGERS:
            return "node"
        if name == "Cargo.lock":
            return "rust"
        return None

    @staticmethod
    def _record_lockfile_ambiguities(
        boundary: str, names: set[str], ambiguities: list[RepositoryAmbiguity]
    ) -> None:
        python_managers = sorted(
            {name.removesuffix(".lock") for name in names & {"uv.lock", "poetry.lock"}}
        )
        if len(python_managers) > 1:
            paths = [
                StaticRepositoryProfiler._join(boundary, f"{name}.lock") for name in python_managers
            ]
            ambiguities.append(
                StaticRepositoryProfiler._ambiguity(
                    "conflicting_python_lockfiles",
                    f"Multiple Python managers are declared at {boundary}: "
                    f"{', '.join(python_managers)}.",
                    paths,
                )
            )
        node_managers = sorted(
            {_LOCKFILE_MANAGERS[name] for name in names & _LOCKFILE_MANAGERS.keys()}
        )
        if len(node_managers) > 1:
            paths = sorted(
                StaticRepositoryProfiler._join(boundary, name)
                for name in names
                if name in _LOCKFILE_MANAGERS
            )
            ambiguities.append(
                StaticRepositoryProfiler._ambiguity(
                    "conflicting_node_lockfiles",
                    f"Multiple Node managers are declared at {boundary}: "
                    f"{', '.join(node_managers)}.",
                    paths,
                )
            )

    @staticmethod
    def _python(
        candidate: _Candidate, text: str, names: set[str]
    ) -> tuple[set[str], list[RepositoryCommand]]:
        data = tomllib.loads(text)
        systems = {"python"}
        tool = data.get("tool", {})
        if not isinstance(tool, dict):
            raise TypeError("[tool] must be a table")
        managers = []
        if "uv.lock" in names or "uv" in tool:
            systems.add("uv")
            managers.append("uv")
        if "poetry.lock" in names or "poetry" in tool:
            systems.add("poetry")
            managers.append("poetry")
        manager = managers[0] if len(managers) == 1 else None
        command_specs: list[tuple[str, str, list[str], str, str]] = []
        dependencies = StaticRepositoryProfiler._python_dependencies(data)
        if "pytest" in tool or "pytest" in dependencies:
            command_specs.append(
                ("python-test", "test", ["pytest"], "tool.pytest/dependencies", "high")
            )
        if "ruff" in tool or "ruff" in dependencies:
            command_specs.append(
                ("python-lint", "lint", ["ruff", "check", "."], "tool.ruff/dependencies", "high")
            )
        if "mypy" in tool or "mypy" in dependencies:
            command_specs.append(
                ("python-typecheck", "check", ["mypy"], "tool.mypy/dependencies", "high")
            )
        if "build-system" in data:
            command_specs.append(("python-build", "build", ["build"], "build-system", "medium"))
        commands = [
            StaticRepositoryProfiler._python_command(candidate, manager, *spec)
            for spec in command_specs
        ]
        return systems, commands

    @staticmethod
    def _python_dependencies(data: dict[str, Any]) -> set[str]:
        values: list[Any] = []
        project = data.get("project", {})
        if isinstance(project, dict):
            values.extend(project.get("dependencies", []) or [])
            optional = project.get("optional-dependencies", {})
            if isinstance(optional, dict):
                for group in optional.values():
                    if isinstance(group, list):
                        values.extend(group)
        poetry = (
            data.get("tool", {}).get("poetry", {}) if isinstance(data.get("tool"), dict) else {}
        )
        if isinstance(poetry, dict):
            dependencies = poetry.get("dependencies", {})
            if isinstance(dependencies, dict):
                values.extend(dependencies.keys())
            groups = poetry.get("group", {})
            if isinstance(groups, dict):
                for group in groups.values():
                    if not isinstance(group, dict):
                        continue
                    group_dependencies = group.get("dependencies", {})
                    if isinstance(group_dependencies, dict):
                        values.extend(group_dependencies.keys())
        names: set[str] = set()
        for value in values:
            match = re.match(r"[A-Za-z0-9_.-]+", str(value))
            if match:
                names.add(match.group(0).lower())
        return names

    @staticmethod
    def _python_command(
        candidate: _Candidate,
        manager: str | None,
        name: str,
        purpose: str,
        raw: list[str],
        pointer: str,
        confidence: str,
    ) -> RepositoryCommand:
        if raw == ["build"] and manager in {"uv", "poetry"}:
            executable, argv = manager, ["build"]
        elif manager in {"uv", "poetry"}:
            executable, argv = manager, ["run", *raw]
        elif raw == ["pytest"]:
            executable, argv = "python", ["-m", "pytest"]
        elif raw == ["build"]:
            executable, argv = "python", ["-m", "build"]
        else:
            executable, argv = raw[0], raw[1:]
        return StaticRepositoryProfiler._command(
            candidate, name, purpose, executable, argv, pointer, confidence
        )

    @staticmethod
    def _node(
        candidate: _Candidate, text: str, names: set[str]
    ) -> tuple[set[str], list[RepositoryCommand]]:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise TypeError("package.json root must be an object")
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict):
            raise TypeError("package.json scripts must be an object")
        if len(scripts) > MAX_NODE_SCRIPTS:
            raise ValueError(f"package.json declares more than {MAX_NODE_SCRIPTS} scripts")
        lock_managers = sorted(
            {_LOCKFILE_MANAGERS[name] for name in names & _LOCKFILE_MANAGERS.keys()}
        )
        declared = data.get("packageManager")
        declared_manager = None
        if declared is not None:
            if not isinstance(declared, str):
                raise TypeError("packageManager must be a string")
            declared_manager = declared.split("@", 1)[0]
            if declared_manager not in {"npm", "pnpm", "yarn", "bun"}:
                declared_manager = None
        manager = declared_manager or (lock_managers[0] if len(lock_managers) == 1 else None)
        confidence = "high"
        systems = {"node", *lock_managers}
        if declared_manager is not None:
            systems.add(declared_manager)
        commands = []
        for script_name, script_body in sorted(scripts.items()):
            if not isinstance(script_name, str) or not isinstance(script_body, str):
                raise TypeError("package.json scripts must map strings to strings")
            if manager is None:
                continue
            commands.append(
                StaticRepositoryProfiler._command(
                    candidate,
                    f"node-{script_name}",
                    StaticRepositoryProfiler._script_purpose(script_name),
                    manager,
                    ["run", script_name],
                    f"/scripts/{script_name}",
                    confidence,
                )
            )
        return systems, commands

    @staticmethod
    def _go(candidate: _Candidate, text: str) -> tuple[set[str], list[RepositoryCommand]]:
        if not any(line.strip().startswith("module ") for line in text.splitlines()):
            raise ValueError("go.mod has no module directive")
        return {"go"}, [
            StaticRepositoryProfiler._command(
                candidate, "go-test", "test", "go", ["test", "./..."], "module", "high"
            ),
            StaticRepositoryProfiler._command(
                candidate, "go-vet", "lint", "go", ["vet", "./..."], "module", "high"
            ),
            StaticRepositoryProfiler._command(
                candidate, "go-build", "build", "go", ["build", "./..."], "module", "high"
            ),
        ]

    @staticmethod
    def _rust(candidate: _Candidate, text: str) -> tuple[set[str], list[RepositoryCommand]]:
        data = tomllib.loads(text)
        if not isinstance(data.get("package") or data.get("workspace"), dict):
            raise ValueError("Cargo.toml requires [package] or [workspace]")
        return {"cargo", "rust"}, [
            StaticRepositoryProfiler._command(
                candidate, "rust-test", "test", "cargo", ["test"], "Cargo.toml", "high"
            ),
            StaticRepositoryProfiler._command(
                candidate,
                "rust-clippy",
                "lint",
                "cargo",
                ["clippy", "--all-targets", "--all-features"],
                "Cargo.toml",
                "medium",
            ),
            StaticRepositoryProfiler._command(
                candidate, "rust-build", "build", "cargo", ["build"], "Cargo.toml", "high"
            ),
        ]

    @staticmethod
    def _maven(
        candidate: _Candidate, text: str, names: set[str]
    ) -> tuple[set[str], list[RepositoryCommand]]:
        ElementTree.fromstring(text)
        executable = "./mvnw" if "mvnw" in names else "mvn"
        return {"maven"}, [
            StaticRepositoryProfiler._command(
                candidate, "maven-test", "test", executable, ["test"], "pom.xml", "high"
            ),
            StaticRepositoryProfiler._command(
                candidate, "maven-build", "build", executable, ["package"], "pom.xml", "high"
            ),
        ]

    @staticmethod
    def _gradle(candidate: _Candidate, names: set[str]) -> tuple[set[str], list[RepositoryCommand]]:
        executable = "./gradlew" if "gradlew" in names else "gradle"
        return {"gradle"}, [
            StaticRepositoryProfiler._command(
                candidate, "gradle-test", "test", executable, ["test"], candidate.path.name, "high"
            ),
            StaticRepositoryProfiler._command(
                candidate,
                "gradle-build",
                "build",
                executable,
                ["build"],
                candidate.path.name,
                "high",
            ),
        ]

    @staticmethod
    def _make(candidate: _Candidate, text: str) -> tuple[set[str], list[RepositoryCommand]]:
        targets: set[str] = set()
        for line in text.splitlines():
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)\s*:(?!=)", line)
            if match and "%" not in match.group(1):
                targets.add(match.group(1))
        commands = []
        for target in sorted(targets):
            purpose = StaticRepositoryProfiler._script_purpose(target)
            if purpose != "other":
                commands.append(
                    StaticRepositoryProfiler._command(
                        candidate,
                        f"make-{target}",
                        purpose,
                        "make",
                        [target],
                        f"target:{target}",
                        "high",
                    )
                )
        return {"make"}, commands

    @staticmethod
    def _validate_workflow(text: str) -> None:
        for token in yaml.scan(text):
            if isinstance(token, (AliasToken, AnchorToken)):
                raise ValueError("GitHub Actions anchors and aliases are not profiled")
        value = yaml.safe_load(text)
        if not isinstance(value, dict) or "jobs" not in value:
            raise ValueError("GitHub Actions workflow root must contain jobs")

    @staticmethod
    def _command(
        candidate: _Candidate,
        name: str,
        purpose: str,
        executable: str,
        argv: list[str],
        pointer: str,
        confidence: str,
    ) -> RepositoryCommand:
        return RepositoryCommand(
            name=name,
            purpose=purpose,
            executable=executable,
            argv=argv,
            cwd=StaticRepositoryProfiler._boundary_for(candidate.relative),
            provenance=CommandProvenance(
                path=candidate.relative,
                source="static-manifest",
                pointer=pointer,
            ),
            confidence=confidence,
            execution_authorized=False,
        )

    @staticmethod
    def _script_purpose(name: str) -> str:
        lowered = name.lower()
        if lowered == "test" or lowered.startswith("test:") or lowered.startswith("test-"):
            return "test"
        if lowered in {"lint", "format", "fmt"} or lowered.startswith(("lint:", "lint-")):
            return "lint"
        if lowered == "build" or lowered.startswith(("build:", "build-")):
            return "build"
        if lowered in {"check", "typecheck", "type-check", "verify"}:
            return "check"
        return "other"

    @staticmethod
    def _deduplicate_commands(commands: list[RepositoryCommand]) -> list[RepositoryCommand]:
        by_key: dict[tuple[str, str, tuple[str, ...]], RepositoryCommand] = {}
        for command in commands:
            key = (command.cwd, command.executable, tuple(command.argv))
            by_key.setdefault(key, command)
        return sorted(
            by_key.values(),
            key=lambda item: (item.cwd, item.purpose, item.executable, item.argv, item.name),
        )

    @staticmethod
    def _summary(profile: RepositoryProfile) -> str:
        ecosystems = ", ".join(profile.ecosystems) or "no supported ecosystem"
        return (
            f"Static profile detected {ecosystems} across {len(profile.boundaries)} "
            f"repository boundary/boundaries and {len(profile.commands)} unapproved "
            "command candidate(s)."
        )

    @staticmethod
    def _join(boundary: str, name: str) -> str:
        return name if boundary == "." else f"{boundary}/{name}"

    @staticmethod
    def _ambiguity(code: str, message: str, paths: list[str] | None = None) -> RepositoryAmbiguity:
        return RepositoryAmbiguity(code=code, message=message, paths=sorted(paths or []))


# Alternate descriptive name for callers; both names refer to the same adapter.
StaticRepositoryProfileAdapter = StaticRepositoryProfiler
