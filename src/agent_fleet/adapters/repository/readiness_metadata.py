"""Pure in-memory projection of metadata already read by the static profiler."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Literal, cast

from pydantic import ValidationError

from agent_fleet.domain.readiness import (
    MAX_READINESS_DECLARATIONS,
    MAX_READINESS_DIAGNOSTICS,
    MAX_READINESS_MANIFESTS,
    DiagnosticCode,
    ReadinessDiagnostic,
    StaticDeclaration,
    StaticManifest,
    StaticReadinessMetadata,
)
from agent_fleet.domain.security import sha256_bytes

_NAME = re.compile(r"(?:@[A-Za-z0-9][A-Za-z0-9._-]*/)?[A-Za-z0-9][A-Za-z0-9._-]{0,100}\Z")
_REQUIREMENT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9_,.-]+\])?\s*(.*)\Z")
_CONSTRAINT = re.compile(r"[A-Za-z0-9.*<>=!~^|, +_-]{1,256}\Z")


class MetadataCapture:
    """No paths are opened here; all limits are across the single profiling pass."""

    def __init__(self) -> None:
        self.manifests: list[StaticManifest] = []
        self.declarations: list[StaticDeclaration] = []
        self.diagnostics: list[ReadinessDiagnostic] = []
        self.omitted_manifests = 0
        self.omitted_declarations = 0
        self.omitted_diagnostics = 0

    def observe(self, path: str, filename: str, text: str) -> None:
        if filename not in {"pyproject.toml", "package.json"}:
            return
        if len(self.manifests) >= MAX_READINESS_MANIFESTS:
            self.omitted_manifests += 1
            self.issue("manifest_limit")
            return
        ecosystem: Literal["python", "node"] = "python" if filename == "pyproject.toml" else "node"
        try:
            manifest = StaticManifest(
                path=path, ecosystem=ecosystem, sha256=sha256_bytes(text.encode("utf-8"))
            )
            self.manifests.append(manifest)
            data: object = tomllib.loads(text) if ecosystem == "python" else json.loads(text)
            if not isinstance(data, dict):
                self.issue("invalid_declaration", path)
                return
            if ecosystem == "python":
                self._python(path, data)
            else:
                self._node(path, data)
        except (ValueError, TypeError, RecursionError):
            # Never retain parser text, a raw declaration or exception details.
            self.issue("metadata_capture_failed")

    def issue(self, code: DiagnosticCode, path: str | None = None) -> None:
        if len(self.diagnostics) >= MAX_READINESS_DIAGNOSTICS:
            self.omitted_diagnostics += 1
            return
        try:
            diagnostic = ReadinessDiagnostic(code=code, path=path)
        except ValidationError:
            diagnostic = ReadinessDiagnostic(code="unsafe_projection")
        self.diagnostics.append(diagnostic)

    def finish(self) -> StaticReadinessMetadata:
        return StaticReadinessMetadata(
            manifests=tuple(self.manifests),
            declarations=tuple(self.declarations),
            diagnostics=tuple(self.diagnostics),
            omitted_manifests=self.omitted_manifests,
            omitted_declarations=self.omitted_declarations,
            omitted_diagnostics=self.omitted_diagnostics,
        )

    def _add(self, **values: object) -> None:
        if len(self.declarations) >= MAX_READINESS_DECLARATIONS:
            self.omitted_declarations += 1
            self.issue("declaration_limit")
            return
        try:
            self.declarations.append(StaticDeclaration.model_validate(values))
        except ValidationError:
            self.issue("invalid_declaration")

    @staticmethod
    def _name(value: object) -> str | None:
        # Preserve admitted spelling so exact registered-secret checks cannot be
        # defeated by normalization before the application projects this metadata.
        return value if isinstance(value, str) and _NAME.fullmatch(value) else None

    @staticmethod
    def _source(value: str) -> Literal["registry", "url", "vcs", "path", "workspace"]:
        lowered = value.lower().strip()
        if any(
            token in lowered for token in ("git+", "git:", "git@", "github:", "hg+", "svn+", "bzr+")
        ):
            return "vcs"
        if "://" in lowered or lowered.startswith(("http:", "https:", "ssh:")):
            return "url"
        if lowered.startswith("workspace:"):
            return "workspace"
        if lowered.startswith(("file:", "link:", ".", "/", "~")):
            return "path"
        return "registry"

    def _dependency(
        self,
        path: str,
        ecosystem: Literal["python", "node"],
        category: str,
        value: object,
        *,
        name: object = None,
        group: str | None = None,
    ) -> None:
        if not isinstance(value, str) or len(value) > 4096:
            self.issue("invalid_declaration", path)
            return
        source = self._source(value)
        constraint: str | None = None
        package = self._name(name)
        remaining = value.strip()
        if ecosystem == "python" and source == "registry":
            match = _REQUIREMENT.fullmatch(remaining)
            if match is None:
                self.issue("invalid_declaration", path)
                return
            package = self._name(match.group(1))
            if remaining[len(match.group(1)) :].startswith("["):
                # Optional extras are not resolved by this static first slice.
                self.issue("unsupported_metadata", path)
            remaining = match.group(2).strip()
            if remaining.startswith("@"):
                source = self._source(remaining[1:].strip())
                if source == "registry":
                    source = "path"
        elif ecosystem == "python":
            match = _REQUIREMENT.fullmatch(remaining)
            if match is not None and match.group(2).lstrip().startswith("@"):
                package = self._name(match.group(1))
        if source != "registry":
            self.issue("unsupported_dependency_source", path)
        elif package is None:
            self.issue("invalid_declaration", path)
            return
        elif remaining:
            if ";" in remaining:
                # Conditional selection is intentionally not evaluated or retained.
                remaining = remaining.partition(";")[0].strip()
                self.issue("unsupported_metadata", path)
            if remaining and _CONSTRAINT.fullmatch(remaining):
                constraint = remaining
            elif remaining:
                self.issue("invalid_declaration", path)
                return
        self._add(
            manifest_path=path,
            ecosystem=ecosystem,
            category=category,
            name=package,
            group=group,
            constraint=constraint,
            source_type=source,
        )

    def _python(self, path: str, data: dict[str, object]) -> None:
        project = data.get("project", {})
        if not isinstance(project, dict):
            self.issue("invalid_declaration", path)
            return
        requires = project.get("requires-python")
        if requires is not None:
            if isinstance(requires, str) and _CONSTRAINT.fullmatch(requires):
                self._add(
                    manifest_path=path,
                    ecosystem="python",
                    category="requires_python",
                    name="python",
                    constraint=requires,
                    source_type="registry",
                )
            else:
                self.issue("invalid_declaration", path)
        self._python_list(path, project.get("dependencies", []), "dependency")
        optional = project.get("optional-dependencies", {})
        self._python_groups(path, optional, "optional_dependency")
        self._python_groups(path, data.get("dependency-groups", {}), "dependency_group")
        dynamic = project.get("dynamic", [])
        if not isinstance(dynamic, list):
            self.issue("invalid_declaration", path)
        elif dynamic:
            self.issue("dynamic_declaration", path)
            self._add(
                manifest_path=path, ecosystem="python", category="dynamic", source_type="dynamic"
            )
        tool = data.get("tool", {})
        if isinstance(tool, dict) and "poetry" in tool:
            self.issue("unsupported_metadata", path)
        if isinstance(tool, dict) and isinstance(tool.get("uv"), dict):
            uv = tool["uv"]
            if "sources" in uv:
                # These can override otherwise registry-looking project declarations.
                # Do not retain or resolve their local/VCS/credential-bearing payloads.
                self.issue("unsupported_metadata", path)

    def _python_groups(self, path: str, groups: object, category: str) -> None:
        if not isinstance(groups, dict):
            self.issue("invalid_declaration", path)
            return
        for name, values in sorted(groups.items()):
            group = self._name(name)
            if group is None:
                self.issue("invalid_declaration", path)
            else:
                self._python_list(path, values, category, group=group)

    def _python_list(
        self, path: str, values: object, category: str, *, group: str | None = None
    ) -> None:
        if not isinstance(values, list):
            self.issue("invalid_declaration", path)
            return
        for value in values:
            if isinstance(value, dict):
                self.issue("unsupported_metadata", path)
            else:
                self._dependency(path, "python", category, value, group=group)

    def _node(self, path: str, data: dict[str, object]) -> None:
        manager = data.get("packageManager")
        if manager is not None:
            if isinstance(manager, str):
                name, separator, version = manager.partition("@")
                if (
                    name in {"npm", "pnpm", "yarn", "bun"}
                    and separator
                    and _CONSTRAINT.fullmatch(version)
                ):
                    self._add(
                        manifest_path=path,
                        ecosystem="node",
                        category="package_manager",
                        name=name,
                        constraint=version,
                        source_type="registry",
                    )
                else:
                    self.issue("invalid_declaration", path)
            else:
                self.issue("invalid_declaration", path)
        engines = data.get("engines", {})
        if not isinstance(engines, dict):
            self.issue("invalid_declaration", path)
        else:
            for name, version in sorted(engines.items()):
                if (
                    self._name(name) is not None
                    and isinstance(version, str)
                    and _CONSTRAINT.fullmatch(version)
                ):
                    self._add(
                        manifest_path=path,
                        ecosystem="node",
                        category="engine",
                        name=self._name(name),
                        constraint=version,
                        source_type="registry",
                    )
                else:
                    self.issue("invalid_declaration", path)
        for key, category in (
            ("dependencies", "dependency"),
            ("devDependencies", "dev_dependency"),
            ("optionalDependencies", "optional_dependency"),
        ):
            values = data.get(key, {})
            if not isinstance(values, dict):
                self.issue("invalid_declaration", path)
                continue
            for dependency_name, dependency_version in sorted(
                cast(dict[str, object], values).items()
            ):
                self._dependency(path, "node", category, dependency_version, name=dependency_name)
