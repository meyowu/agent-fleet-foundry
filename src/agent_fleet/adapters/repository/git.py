"""Git repository/worktree adapter using only structured subprocess argv."""

from __future__ import annotations

import os
import re
import subprocess
from contextlib import suppress
from functools import lru_cache
from pathlib import Path

from agent_fleet.adapters.executable_resolution import (
    resolve_trusted_executable,
    trusted_search_path,
)
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ApplyResult,
    PatchInfo,
    RepositoryInfo,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.offline_canary import (
    BOOTSTRAP_HOST_SENTINEL_NAME,
    BOOTSTRAP_SANDBOX_PROBE_MARKER,
    BROKEN_CANARY,
)
from agent_fleet.domain.security import (
    MINIMUM_GIT_VERSION,
    canonical_json_hash,
    git_version_is_supported,
    resolve_logical_path,
    sha256_bytes,
    status_fingerprint,
)
from agent_fleet.ports.id_generator import IdGenerator

_GIT_TIMEOUT_SECONDS = 30
_EXECUTABLE_CONFIG_QUERY = (
    r"^(filter\..*\.(clean|smudge|process|required)|"
    r"diff\..*\.(command|textconv|cachetextconv)|"
    r"hook\..*\.(command|event)|include\.path|includeif\..*\.path|"
    r"core\.(gitproxy|alternaterefscommand))$"
)
_ALLOWED_GIT_SUBCOMMANDS = frozenset(
    {
        "add",
        "apply",
        "cat-file",
        "commit",
        "config",
        "diff",
        "init",
        "ls-files",
        "read-tree",
        "rev-parse",
        "status",
        "worktree",
    }
)
_OBJECT_ID = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class GitRepositoryAdapter:
    def __init__(self, state_root: Path, ids: IdGenerator) -> None:
        self._state_root_input = Path(os.path.abspath(state_root))
        self.state_root = self._state_root_input.resolve()
        self.workspace_root = self.state_root / "workspaces"
        self.ids = ids
        self._git_binary: str | None = None

    def inspect(self, root: Path) -> RepositoryInfo:
        supplied_root = Path(os.path.abspath(root))
        repository_identity: tuple[Path, Path, Path, str] | None = None
        try:
            requested = supplied_root.resolve()
            extra_untrusted_roots = (supplied_root,)
            requested_identity = self._discover_repository_identity(
                requested,
                extra_untrusted_roots=extra_untrusted_roots,
            )
            canonical_root = requested_identity[0]
            requested_common_dir = requested_identity[2]
            requested.relative_to(canonical_root)
            canonical_identity = self._discover_repository_identity(
                canonical_root,
                extra_untrusted_roots=extra_untrusted_roots,
            )
            if canonical_identity != requested_identity:
                raise ValueError(
                    "Git repository identity changed between requested path and top-level root"
                )
            head = self._run(
                ["git", "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}"],
                cwd=canonical_root,
                extra_untrusted_roots=extra_untrusted_roots,
            ).strip()
            if _OBJECT_ID.fullmatch(head) is None:
                raise ValueError("Git returned an invalid HEAD object ID")
            repository_identity = (*canonical_identity, head)
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
        if repository_identity is None:
            raise FleetError(
                ErrorCode.PROJECT_NOT_GIT,
                "The requested path is not a usable Git repository.",
                "Initialize and commit a Git repository, then retry.",
            )
        canonical_root, _, requested_common_dir, head = repository_identity
        extra_untrusted_roots = (supplied_root,)
        status = self._run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=all",
                "--no-renames",
                "-z",
            ],
            cwd=canonical_root,
            extra_untrusted_roots=extra_untrusted_roots,
        )
        remote = self._run(
            ["git", "config", "--local", "--no-includes", "--get", "remote.origin.url"],
            cwd=canonical_root,
            check=False,
            extra_untrusted_roots=extra_untrusted_roots,
        ).strip()
        remote_fingerprint = f"sha256:{sha256_bytes(remote.encode())}" if remote else None
        identity_hash = canonical_json_hash(
            {
                "git_common_dir": str(requested_common_dir),
                "remote": remote_fingerprint,
            }
        )
        entries = [entry for entry in status.split("\x00") if entry]
        dirty_paths = sorted({entry[3:] for entry in entries if len(entry) >= 4})
        return RepositoryInfo(
            root=str(canonical_root),
            head_revision=head,
            remote_fingerprint=remote_fingerprint,
            identity_hash=identity_hash,
            status_porcelain=status,
            status_fingerprint=status_fingerprint(status),
            dirty_paths=dirty_paths,
        )

    def _discover_repository_identity(
        self,
        cwd: Path,
        *,
        extra_untrusted_roots: tuple[Path, ...] = (),
    ) -> tuple[Path, Path, Path]:
        output = self._run(
            [
                "git",
                "rev-parse",
                "--path-format=absolute",
                "--show-toplevel",
                "--absolute-git-dir",
                "--git-common-dir",
            ],
            cwd=cwd,
            extra_untrusted_roots=extra_untrusted_roots,
        )
        values = output.splitlines()
        if len(values) != 3 or any(not value for value in values):
            raise ValueError("Git returned malformed repository identity output")
        top_level, git_dir, common_dir = (Path(value).resolve(strict=True) for value in values)
        return top_level, git_dir, common_dir

    def create_workspace(
        self,
        repository_root: Path,
        run_id: str,
        base_revision: str,
        kind: WorkspaceKind,
    ) -> Workspace:
        if _OBJECT_ID.fullmatch(base_revision) is None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Workspace base revision must be a full Git object ID.",
                "Inspect the repository again and use its exact HEAD revision.",
            )
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        workspace_id = self.ids.new(IdPrefix.WORKSPACE)
        path = self.workspace_root / run_id / f"{kind.value}-{workspace_id}"
        if path.exists():
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                f"Fleet workspace path already exists: {path.name}.",
                "Run recovery before retrying the workflow.",
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._run(
                [
                    "git",
                    "worktree",
                    "add",
                    "--detach",
                    "--no-checkout",
                    str(path),
                    base_revision,
                ],
                cwd=repository_root.resolve(strict=True),
            )
            self._run(["git", "read-tree", base_revision], cwd=path)
            self._materialize_index(path)
        except (OSError, subprocess.CalledProcessError) as error:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Git could not create the Fleet-owned worktree.",
                "Inspect `git worktree list` and remove only stale Fleet-owned worktrees.",
            ) from error
        return Workspace(
            workspace_id=workspace_id,
            run_id=run_id,
            kind=kind,
            path=str(path.resolve(strict=True)),
            base_revision=base_revision,
        )

    def apply_patch_to_workspace(self, workspace: Workspace, patch: bytes) -> None:
        path = self._validated_workspace_path(workspace)
        try:
            self._run_bytes(
                ["git", "apply", "--whitespace=nowarn", "-"], cwd=path, input_bytes=patch
            )
        except subprocess.CalledProcessError as error:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Candidate patch could not be reconstructed in the verification workspace.",
                "Inspect the patch artifact and rerun the task.",
            ) from error

    def compute_patch(self, workspace: Workspace) -> PatchInfo:
        path = self._validated_workspace_path(workspace)
        patch = self._run_bytes(
            [
                "git",
                "diff",
                "--binary",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=all",
                "--no-renames",
                "--src-prefix=a/",
                "--dst-prefix=b/",
            ],
            cwd=path,
        )
        changed = self._run_bytes(
            [
                "git",
                "diff",
                "--name-only",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=all",
                "--no-renames",
                "-z",
            ],
            cwd=path,
        )
        changed_paths = sorted(
            item.decode("utf-8", errors="surrogateescape")
            for item in changed.split(b"\x00")
            if item
        )
        return PatchInfo(
            content=patch.decode("utf-8", errors="strict"),
            sha256=sha256_bytes(patch),
            changed_paths=changed_paths,
        )

    def workspace_status_fingerprint(self, workspace: Workspace) -> str:
        path = self._validated_workspace_path(workspace)
        status = self._run(
            [
                "git",
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "--ignore-submodules=all",
                "--no-renames",
                "-z",
            ],
            cwd=path,
        )
        return status_fingerprint(status)

    def apply_patch_to_target(
        self,
        repository_root: Path,
        patch: bytes,
        expected_identity_hash: str,
        expected_base_revision: str,
        expected_status_fingerprint: str,
    ) -> ApplyResult:
        current = self.inspect(repository_root)
        if (
            current.identity_hash != expected_identity_hash
            or current.head_revision != expected_base_revision
            or current.status_fingerprint != expected_status_fingerprint
        ):
            raise FleetError(
                ErrorCode.PATCH_TARGET_DIVERGED,
                "The target repository identity, revision, or working-tree state "
                "changed since the run.",
                "Preserve your work, restore the recorded target state, or start a new Fleet run.",
                details={
                    "expected_base": expected_base_revision,
                    "actual_base": current.head_revision,
                    "working_tree_changed": current.status_fingerprint
                    != expected_status_fingerprint,
                },
            )
        root = Path(current.root)
        try:
            self._run_bytes(["git", "apply", "--check", "-"], cwd=root, input_bytes=patch)
            names = self._run_bytes(
                ["git", "apply", "--numstat", "-z", "-"],
                cwd=root,
                input_bytes=patch,
            )
            self._run_bytes(
                ["git", "apply", "--whitespace=nowarn", "-"], cwd=root, input_bytes=patch
            )
        except subprocess.CalledProcessError as error:
            raise FleetError(
                ErrorCode.PATCH_TARGET_DIVERGED,
                "The candidate patch no longer applies cleanly to the target repository.",
                "Leave current files untouched and start a new run from the current revision.",
            ) from error
        changed_paths = _parse_numstat_paths(names)
        return ApplyResult(
            applied=True,
            head_revision=current.head_revision,
            changed_paths=changed_paths,
        )

    def cleanup_workspace(self, repository_root: Path, workspace: Workspace) -> None:
        path = self._validated_workspace_path(workspace, require_exists=False)
        if not path.exists():
            return
        try:
            self._run(
                ["git", "worktree", "remove", "--force", str(path)],
                cwd=repository_root.resolve(strict=True),
            )
        except subprocess.CalledProcessError as error:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                f"Could not clean Fleet-owned worktree {workspace.workspace_id}.",
                "Run recovery after confirming the path is below the Fleet state directory.",
            ) from error

    def create_canary_fixture(self, destination: Path) -> Path:
        self.state_root.mkdir(parents=True, exist_ok=True)
        target = resolve_logical_path(
            self.state_root,
            str(destination.resolve().relative_to(self.state_root)),
            allow_missing=True,
        )
        if (target / ".git").exists():
            return target
        target.mkdir(parents=True, exist_ok=False)
        (target / "src/canary_calc").mkdir(parents=True)
        (target / "tests").mkdir()
        (target / "pyproject.toml").write_text(
            "[build-system]\nrequires = []\nbuild-backend = 'builtins'\n\n"
            "[project]\nname = 'canary-calc'\nversion = '0.0.0'\nrequires-python = '>=3.12'\n\n"
            "[project.optional-dependencies]\ntest = ['pytest>=8']\n",
            encoding="utf-8",
        )
        (target / "src/canary_calc/__init__.py").write_text(
            "from .core import divide\n\n__all__ = ['divide']\n", encoding="utf-8"
        )
        (target / "src/canary_calc/core.py").write_text(BROKEN_CANARY, encoding="utf-8")
        (target / "tests/test_core.py").write_text(
            "import pytest\n\nfrom canary_calc import divide\n\n\n"
            "def test_divide_by_zero_has_stable_error() -> None:\n"
            "    with pytest.raises(ValueError, match='division by zero is not allowed'):\n"
            "        divide(1, 0)\n",
            encoding="utf-8",
        )
        self._run(["git", "init", "--template=", "--initial-branch=main"], cwd=target)
        self._run(
            [
                "git",
                "add",
                "--",
                "pyproject.toml",
                "src/canary_calc/__init__.py",
                "src/canary_calc/core.py",
                "tests/test_core.py",
            ],
            cwd=target,
        )
        self._run(
            [
                "git",
                "commit",
                "--no-gpg-sign",
                "--no-verify",
                "--no-status",
                "-m",
                "canary baseline",
            ],
            cwd=target,
        )
        return target

    def create_bootstrap_canary_fixture(self, destination: Path) -> Path:
        """Create the trusted dependency-free Phase 3 bootstrap canary."""

        self.state_root.mkdir(parents=True, exist_ok=True)
        target = resolve_logical_path(
            self.state_root,
            str(destination.resolve().relative_to(self.state_root)),
            allow_missing=True,
        )
        if (target / ".git").exists():
            return target
        target.mkdir(parents=True, exist_ok=False)
        host_sentinel = target.parent / BOOTSTRAP_HOST_SENTINEL_NAME
        host_sentinel.write_text("Fleet-owned host sentinel\n", encoding="utf-8")
        (target / "src/canary_calc").mkdir(parents=True)
        (target / "tests").mkdir()
        (target / "pyproject.toml").write_text(
            "[project]\nname = 'agent-fleet-bootstrap-canary'\n"
            "version = '0.0.0'\nrequires-python = '>=3.12'\n",
            encoding="utf-8",
        )
        (target / "src/canary_calc/__init__.py").write_text(
            "from .core import divide\n\n__all__ = ['divide']\n", encoding="utf-8"
        )
        (target / "src/canary_calc/core.py").write_text(BROKEN_CANARY, encoding="utf-8")
        (target / "tests/test_core.py").write_text(
            "import sys\n"
            "import unittest\n"
            "from pathlib import Path\n\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n\n"
            "from canary_calc import divide\n\n\n"
            "class DivideTests(unittest.TestCase):\n"
            "    def test_divide_by_zero_has_stable_error(self) -> None:\n"
            "        with self.assertRaisesRegex(\n"
            "            ValueError, 'division by zero is not allowed'\n"
            "        ):\n"
            "            divide(1, 0)\n\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        (target / "tests/test_sandbox_boundary.py").write_text(
            "import os\n"
            "import unittest\n"
            "from pathlib import Path\n\n"
            f"HOST_SENTINEL = Path({str(host_sentinel)!r})\n"
            "ALLOWED_ENVIRONMENT_NAMES = {\n"
            "    'HOME', 'HOSTNAME', 'LANG', 'LC_ALL', 'PATH'\n"
            "}\n"
            "SENSITIVE_NAME_PARTS = (\n"
            "    'credential', 'key', 'password', 'secret', 'token'\n"
            ")\n\n"
            "class SandboxBoundaryTests(unittest.TestCase):\n"
            "    def test_host_and_environment_boundary(self) -> None:\n"
            "        self.assertFalse(HOST_SENTINEL.exists())\n"
            "        self.assertLessEqual(set(os.environ), ALLOWED_ENVIRONMENT_NAMES)\n"
            "        self.assertFalse(any(\n"
            "            part in name.lower()\n"
            "            for name in os.environ\n"
            "            for part in SENSITIVE_NAME_PARTS\n"
            "        ))\n"
            f"        print({BOOTSTRAP_SANDBOX_PROBE_MARKER!r})\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n",
            encoding="utf-8",
        )
        self._run(["git", "init", "--template=", "--initial-branch=main"], cwd=target)
        self._run(
            [
                "git",
                "add",
                "--",
                "pyproject.toml",
                "src/canary_calc/__init__.py",
                "src/canary_calc/core.py",
                "tests/test_core.py",
                "tests/test_sandbox_boundary.py",
            ],
            cwd=target,
        )
        self._run(
            [
                "git",
                "commit",
                "--no-gpg-sign",
                "--no-verify",
                "--no-status",
                "-m",
                "bootstrap canary baseline",
            ],
            cwd=target,
        )
        return target

    def _validated_workspace_path(
        self, workspace: Workspace, *, require_exists: bool = True
    ) -> Path:
        supplied = Path(workspace.path)
        try:
            logical = str(supplied.resolve().relative_to(self.workspace_root))
        except ValueError as error:
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "Workspace is outside the Fleet-owned workspace root.",
                "Discard the invalid lease and create a new run.",
            ) from error
        return resolve_logical_path(self.workspace_root, logical, allow_missing=not require_exists)

    def _materialize_index(self, workspace_path: Path) -> None:
        """Materialize Git blobs without checkout hooks or configured smudge filters."""

        entries = self._run_bytes(["git", "ls-files", "--stage", "-z"], cwd=workspace_path).split(
            b"\x00"
        )
        for entry in entries:
            if not entry:
                continue
            metadata, path_bytes = entry.split(b"\t", 1)
            mode, object_id, stage = metadata.decode("ascii").split(" ")
            if stage != "0":
                raise FleetError(
                    ErrorCode.RECOVERY_REQUIRED,
                    "A generated worktree unexpectedly contains an unmerged index entry.",
                    "Resolve the source repository index and start a new run.",
                )
            logical_path = path_bytes.decode("utf-8", errors="surrogateescape")
            destination = resolve_logical_path(workspace_path, logical_path, allow_missing=True)
            if mode == "160000":
                destination.mkdir(parents=True, exist_ok=True)
                continue
            content = self._run_bytes(["git", "cat-file", "blob", object_id], cwd=workspace_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                destination.symlink_to(content.decode("utf-8", errors="surrogateescape"))
                continue
            destination.write_bytes(content)
            destination.chmod(0o755 if mode == "100755" else 0o644)

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        check: bool = True,
        extra_untrusted_roots: tuple[Path, ...] = (),
    ) -> str:
        untrusted_roots = (self._state_root_input, *extra_untrusted_roots)
        environment = _git_environment(cwd, self.state_root, *untrusted_roots)
        if argv and Path(argv[0]).name == "git" and self._git_binary is None:
            self._git_binary = _trusted_git_executable(
                argv[0], cwd, self.state_root, *untrusted_roots
            )
        secured_argv = _secure_git_argv(
            argv,
            cwd=cwd,
            state_root=self.state_root,
            environment=environment,
            git_executable=self._git_binary,
            extra_untrusted_roots=untrusted_roots,
        )
        result = subprocess.run(
            secured_argv,
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            env=environment,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        return result.stdout

    def _run_bytes(
        self,
        argv: list[str],
        *,
        cwd: Path,
        input_bytes: bytes | None = None,
        extra_untrusted_roots: tuple[Path, ...] = (),
    ) -> bytes:
        untrusted_roots = (self._state_root_input, *extra_untrusted_roots)
        environment = _git_environment(cwd, self.state_root, *untrusted_roots)
        if argv and Path(argv[0]).name == "git" and self._git_binary is None:
            self._git_binary = _trusted_git_executable(
                argv[0], cwd, self.state_root, *untrusted_roots
            )
        result = subprocess.run(
            _secure_git_argv(
                argv,
                cwd=cwd,
                state_root=self.state_root,
                environment=environment,
                git_executable=self._git_binary,
                extra_untrusted_roots=untrusted_roots,
            ),
            cwd=cwd,
            check=True,
            input=input_bytes,
            capture_output=True,
            env=environment,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        return result.stdout


def _git_environment(
    cwd: Path,
    state_root: Path,
    *extra_untrusted_roots: Path,
) -> dict[str, str]:
    """Build a nonsecret environment with repository/state PATH entries removed."""

    environment = {key: os.environ[key] for key in ("SYSTEMROOT",) if key in os.environ}
    environment["PATH"] = _trusted_search_path(cwd, state_root, *extra_untrusted_roots)
    environment.update(
        {
            "LC_ALL": "C",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "",
            "GIT_EDITOR": "",
            "GIT_SEQUENCE_EDITOR": "",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GIT_AUTHOR_NAME": "Agent Fleet",
            "GIT_AUTHOR_EMAIL": "agent-fleet@example.invalid",
            "GIT_COMMITTER_NAME": "Agent Fleet",
            "GIT_COMMITTER_EMAIL": "agent-fleet@example.invalid",
        }
    )
    return environment


def _base_git_config_args() -> list[str]:
    return [
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.fsmonitor=false",
        "-c",
        f"core.attributesFile={os.devnull}",
        "-c",
        f"core.excludesFile={os.devnull}",
        "-c",
        "diff.external=",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        "-c",
        "credential.helper=",
        "-c",
        "credential.interactive=false",
        "-c",
        "core.askPass=",
        "-c",
        "core.sshCommand=",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "-c",
        "protocol.allow=never",
    ]


def _base_git_global_args() -> list[str]:
    return ["--no-pager", "--no-optional-locks", "--no-replace-objects", "--no-lazy-fetch"]


def _secure_git_argv(
    argv: list[str],
    *,
    cwd: Path,
    state_root: Path,
    environment: dict[str, str],
    git_executable: str | None = None,
    extra_untrusted_roots: tuple[Path, ...] = (),
) -> list[str]:
    if not argv or Path(argv[0]).name != "git":
        return argv
    if any(item in {"-c", "--config-env"} for item in argv[1:]):
        raise ValueError("Git adapter callers may not inject configuration overrides")
    if len(argv) < 2 or argv[1] not in _ALLOWED_GIT_SUBCOMMANDS:
        raise ValueError("Git adapter subcommand is not allow-listed")
    resolved_git = git_executable or _trusted_git_executable(
        argv[0], cwd, state_root, *extra_untrusted_roots
    )
    _require_supported_git(resolved_git, tuple(sorted(environment.items())))
    return [
        resolved_git,
        *_base_git_global_args(),
        *_base_git_config_args(),
        *_repository_execution_config_args(resolved_git, cwd, environment),
        *argv[1:],
    ]


@lru_cache(maxsize=8)
def _require_supported_git(
    git_executable: str,
    environment_items: tuple[tuple[str, str], ...],
) -> None:
    environment = dict(environment_items)
    result = subprocess.run(
        [git_executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=_GIT_TIMEOUT_SECONDS,
    )
    version_output = result.stdout.strip() or result.stderr.strip()
    if result.returncode != 0 or not git_version_is_supported(version_output):
        required = ".".join(str(item) for item in MINIMUM_GIT_VERSION)
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            f"Git {required} or newer is required for hardened repository operations.",
            "Upgrade Git before running Fleet repository commands.",
            details={"detected_version": version_output or "unknown"},
        )


def _repository_execution_config_args(
    git_executable: str,
    cwd: Path,
    environment: dict[str, str],
) -> list[str]:
    """Reject repository-defined execution surfaces before using Git.

    Git has no switch that ignores only repository-local configuration. Reading
    configuration names is non-executing. Any matching key fails closed rather
    than being copied into a later child-process argument.
    """

    probe: subprocess.CompletedProcess[bytes] | None = None
    with suppress(OSError, subprocess.SubprocessError):
        probe = subprocess.run(
            [
                git_executable,
                *_base_git_global_args(),
                *_base_git_config_args(),
                "config",
                "--no-includes",
                "--null",
                "--name-only",
                "--get-regexp",
                _EXECUTABLE_CONFIG_QUERY,
            ],
            cwd=cwd,
            check=False,
            capture_output=True,
            env=environment,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    if probe is None or probe.returncode not in {0, 1}:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "Repository Git configuration could not be checked safely.",
            "Repair the local Git configuration and retry.",
        )
    if probe.stdout:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "Repository Git configuration declares an executable integration surface.",
            "Remove repository-local filter, diff, hook, include, or command configuration "
            "before retrying.",
        )
    return []


def _trusted_search_path(
    cwd: Path,
    state_root: Path,
    *extra_untrusted_roots: Path,
) -> str:
    return trusted_search_path(cwd, state_root, *extra_untrusted_roots)


def _trusted_git_executable(
    requested: str,
    cwd: Path,
    state_root: Path,
    *extra_untrusted_roots: Path,
) -> str:
    candidate = resolve_trusted_executable(
        requested,
        cwd,
        state_root,
        *extra_untrusted_roots,
        expected_name="git",
    )
    if candidate is None:
        raise FleetError(
            ErrorCode.CONFIG_INVALID,
            "A trusted Git executable could not be resolved from absolute PATH entries.",
            "Install Git 2.45 or newer outside the repository and Fleet state directories.",
        )
    return candidate


def _parse_numstat_paths(output: bytes) -> list[str]:
    fields = output.split(b"\x00")
    paths: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if not field:
            continue
        parts = field.split(b"\t", 2)
        if len(parts) != 3:
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Git returned malformed numstat output for the candidate patch.",
                "Recreate the run before applying the patch.",
            )
        path = parts[2]
        if path:
            paths.append(path.decode("utf-8", errors="surrogateescape"))
            continue
        if index + 1 >= len(fields):
            raise FleetError(
                ErrorCode.ARTIFACT_INTEGRITY_FAILED,
                "Git returned an incomplete rename record for the candidate patch.",
                "Recreate the run before applying the patch.",
            )
        old_path = fields[index].decode("utf-8", errors="surrogateescape")
        new_path = fields[index + 1].decode("utf-8", errors="surrogateescape")
        index += 2
        paths.extend([old_path, new_path])
    return sorted(set(paths))
