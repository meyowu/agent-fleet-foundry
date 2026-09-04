"""Git repository/worktree adapter using only structured subprocess argv."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ApplyResult,
    PatchInfo,
    RepositoryInfo,
    Workspace,
    WorkspaceKind,
)
from agent_fleet.domain.security import (
    canonical_json_hash,
    resolve_logical_path,
    sha256_bytes,
    status_fingerprint,
)
from agent_fleet.ports.id_generator import IdGenerator

BROKEN_CANARY = '''"""Tiny deterministic canary."""


def divide(a: float, b: float) -> float:
    return a / b
'''

FIXED_CANARY = '''"""Tiny deterministic canary."""


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("division by zero is not allowed")
    return a / b
'''

INCORRECT_CANARY = '''"""Tiny deterministic canary."""


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("wrong message")
    return a / b
'''


class GitRepositoryAdapter:
    def __init__(self, state_root: Path, ids: IdGenerator) -> None:
        self.state_root = state_root.resolve()
        self.workspace_root = self.state_root / "workspaces"
        self.ids = ids

    def inspect(self, root: Path) -> RepositoryInfo:
        requested = root.resolve()
        try:
            top_level = self._run(["git", "rev-parse", "--show-toplevel"], cwd=requested).strip()
            canonical_root = Path(top_level).resolve(strict=True)
            head = self._run(["git", "rev-parse", "HEAD"], cwd=canonical_root).strip()
        except (OSError, subprocess.CalledProcessError) as error:
            raise FleetError(
                ErrorCode.PROJECT_NOT_GIT,
                f"Path is not a usable Git repository: {requested}.",
                "Initialize and commit a Git repository, then retry.",
            ) from error
        status = self._run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
            cwd=canonical_root,
        )
        git_common = self._run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=canonical_root,
        ).strip()
        remote = self._run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=canonical_root,
            check=False,
        ).strip()
        remote_fingerprint = f"sha256:{sha256_bytes(remote.encode())}" if remote else None
        identity_hash = canonical_json_hash(
            {"git_common_dir": str(Path(git_common).resolve()), "remote": remote_fingerprint}
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

    def create_workspace(
        self,
        repository_root: Path,
        run_id: str,
        base_revision: str,
        kind: WorkspaceKind,
    ) -> Workspace:
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
            self._run(["git", "read-tree", "HEAD"], cwd=path)
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
                "--src-prefix=a/",
                "--dst-prefix=b/",
            ],
            cwd=path,
        )
        changed = self._run_bytes(["git", "diff", "--name-only", "-z"], cwd=path)
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
            ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"], cwd=path
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
            names = self._run_bytes(["git", "apply", "--numstat", "-"], cwd=root, input_bytes=patch)
            self._run_bytes(
                ["git", "apply", "--whitespace=nowarn", "-"], cwd=root, input_bytes=patch
            )
        except subprocess.CalledProcessError as error:
            raise FleetError(
                ErrorCode.PATCH_TARGET_DIVERGED,
                "The candidate patch no longer applies cleanly to the target repository.",
                "Leave current files untouched and start a new run from the current revision.",
            ) from error
        changed_paths = [line.split(b"\t", 2)[-1].decode() for line in names.splitlines() if line]
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
            "[project]\nname = 'canary-calc'\nversion = '0.0.0'\nrequires-python = '>=3.12'\n",
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
        self._run(["git", "init", "--initial-branch=main"], cwd=target)
        self._run(["git", "add", "."], cwd=target)
        self._run(
            [
                "git",
                "-c",
                "user.name=Agent Fleet Test",
                "-c",
                "user.email=agent-fleet@example.invalid",
                "commit",
                "-m",
                "canary baseline",
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

    @staticmethod
    def _run(argv: list[str], *, cwd: Path, check: bool = True) -> str:
        result = subprocess.run(
            _secure_git_argv(argv),
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
            env=_git_environment(),
        )
        return result.stdout

    @staticmethod
    def _run_bytes(argv: list[str], *, cwd: Path, input_bytes: bytes | None = None) -> bytes:
        result = subprocess.run(
            _secure_git_argv(argv),
            cwd=cwd,
            check=True,
            input=input_bytes,
            capture_output=True,
            env=_git_environment(),
        )
        return result.stdout


def _git_environment() -> dict[str, str]:
    """Keep a small nonsecret environment needed to locate Git and system helpers."""

    allowed = ("PATH", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL")
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "Agent Fleet",
            "GIT_AUTHOR_EMAIL": "agent-fleet@example.invalid",
            "GIT_COMMITTER_NAME": "Agent Fleet",
            "GIT_COMMITTER_EMAIL": "agent-fleet@example.invalid",
        }
    )
    return environment


def _secure_git_argv(argv: list[str]) -> list[str]:
    if not argv or Path(argv[0]).name != "git":
        return argv
    return [argv[0], "-c", f"core.hooksPath={os.devnull}", *argv[1:]]
