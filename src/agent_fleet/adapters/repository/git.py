"""Git repository/worktree adapter using only structured subprocess argv."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

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
from agent_fleet.domain.paths import path_is_within
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
_MAX_NEW_FILE_BYTES = 2_000_000
_MAX_NEW_FILES_BYTES = 8_000_000
_MAX_NEW_FILES = 1024
_MAX_PATCH_BYTES = 16_000_000
_PROTECTED_PATCH_COMPONENTS = frozenset({".git", ".fleet"})
_PROTECTED_PATCH_LEAVES = frozenset(
    {".env", ".netrc", ".npmrc", ".pypirc", "credentials", "id_ed25519", "id_rsa"}
)
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
        "hash-object",
        "ls-files",
        "read-tree",
        "rev-parse",
        "status",
        "update-index",
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
        workspace = self.prepare_workspace(run_id, base_revision, kind)
        return self.materialize_workspace(repository_root, workspace)

    def prepare_workspace(self, run_id: str, base_revision: str, kind: WorkspaceKind) -> Workspace:
        """Allocate an exact identity without touching Git or the filesystem."""
        if _OBJECT_ID.fullmatch(base_revision) is None:
            raise FleetError(
                ErrorCode.CONFIG_INVALID,
                "Workspace base revision must be a full Git object ID.",
                "Inspect the repository again and use its exact HEAD revision.",
            )
        workspace_id = self.ids.new(IdPrefix.WORKSPACE)
        path = self.workspace_root / run_id / f"{kind.value}-{workspace_id}"
        return Workspace(
            workspace_id=workspace_id,
            run_id=run_id,
            kind=kind,
            path=str(path),
            base_revision=base_revision,
        )

    def materialize_workspace(self, repository_root: Path, workspace: Workspace) -> Workspace:
        """Create only the preallocated workspace whose lease the caller already saved."""
        expected_path = (
            self.workspace_root
            / workspace.run_id
            / f"{workspace.kind.value}-{workspace.workspace_id}"
        )
        if (
            workspace.path != str(expected_path)
            or _OBJECT_ID.fullmatch(workspace.base_revision) is None
        ):
            raise FleetError(
                ErrorCode.PATH_OUTSIDE_SCOPE,
                "Workspace preparation does not match its exact Fleet-owned identity.",
                "Recover the recorded lease; no alternate workspace path is accepted.",
            )
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        path = self._validated_workspace_path(workspace, require_exists=False)
        if path.exists() or path.is_symlink():
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
                    workspace.base_revision,
                ],
                cwd=repository_root.resolve(strict=True),
            )
            self._run(["git", "read-tree", workspace.base_revision], cwd=path)
            self._materialize_index(path)
        except (OSError, subprocess.CalledProcessError) as error:
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Git could not create the Fleet-owned worktree.",
                "Inspect `git worktree list` and remove only stale Fleet-owned worktrees.",
            ) from error
        return workspace

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

    def patch_changed_paths(self, patch: bytes) -> list[str]:
        if len(patch) > _MAX_PATCH_BYTES:
            raise _unsafe_patch()
        failed = False
        names = b""
        try:
            names = self._run_bytes(
                ["git", "apply", "--numstat", "-z", "-"],
                cwd=self.state_root,
                input_bytes=patch,
            )
        except (OSError, subprocess.CalledProcessError, UnicodeError):
            failed = True
        if failed:
            raise _unsafe_patch()
        return _parse_numstat_paths(names)

    def compute_patch(self, workspace: Workspace) -> PatchInfo:
        path = self._validated_workspace_path(workspace)
        entries = self._run_bytes(["git", "ls-files", "--stage", "-z"], cwd=path)
        tracked_modes = {
            entry.split(b"\t", 1)[1].decode("utf-8", errors="surrogateescape"): entry.split(
                b" ", 1
            )[0].decode("ascii")
            for entry in entries.split(b"\x00")
            if entry
        }
        tracked_objects = {
            entry.split(b"\t", 1)[1].decode("utf-8", errors="surrogateescape"): entry.split(
                b" ", 2
            )[1].decode("ascii")
            for entry in entries.split(b"\x00")
            if entry
        }
        _reject_special_files(
            path, {name for name, mode in tracked_modes.items() if mode == "160000"}
        )
        # Runtime tools do not stage changes. Reject a changed index instead of
        # silently omitting staged content or producing different reconstruction
        # hashes when that content becomes untracked in a fresh verifier.
        if self._run_bytes(
            ["git", "diff", "--cached", "--name-only", "-z", workspace.base_revision, "--"],
            cwd=path,
        ):
            raise _unsafe_patch()
        diff_argv = [
            "git",
            "diff",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "--ignore-submodules=all",
            "--no-renames",
            "--src-prefix=a/",
            "--dst-prefix=b/",
        ]
        changed = self._run_bytes(
            [
                "git",
                "diff",
                "--numstat",
                "--no-ext-diff",
                "--no-textconv",
                "--ignore-submodules=all",
                "--no-renames",
                "-z",
            ],
            cwd=path,
        )
        changed_paths = _parse_numstat_paths(changed)
        if any(field.startswith(b"-\t-\t") for field in changed.split(b"\x00") if field):
            raise _unsafe_patch()
        baseline_size = 0
        for logical_path in changed_paths:
            _validate_patch_path(logical_path)
            if tracked_modes.get(logical_path) not in {"100644", "100755"}:
                raise _unsafe_patch()
            object_id = tracked_objects[logical_path]
            size = int(self._run(["git", "cat-file", "-s", object_id], cwd=path).strip())
            baseline_size += size
            if size > _MAX_NEW_FILE_BYTES or baseline_size > _MAX_NEW_FILES_BYTES:
                raise _unsafe_patch()
        for logical_path in changed_paths:
            _validate_text_patch_content(
                self._run_bytes(
                    ["git", "cat-file", "blob", tracked_objects[logical_path]], cwd=path
                )
            )
        # A changed tracked leaf must also remain a regular bounded file. A
        # deleted leaf is allowed; a symlink replacement must never be packaged.
        existing_changed = [
            name for name in changed_paths if (path / name).exists() or (path / name).is_symlink()
        ]
        snapshot_invalid = False
        tracked_snapshots: list[tuple[str, str, bytes]] = []
        try:
            tracked_snapshots = _snapshot_new_files(path, existing_changed)
        except OSError:
            snapshot_invalid = True
        if snapshot_invalid:
            raise _unsafe_patch()
        patch = self._run_bytes(diff_argv, cwd=path)
        untracked = self._run_bytes(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=path
        )
        invalid = False
        try:
            new_paths = sorted(
                item.decode("utf-8", errors="strict") for item in untracked.split(b"\x00") if item
            )
            if len(new_paths) > _MAX_NEW_FILES:
                raise _unsafe_patch()
            snapshots = _snapshot_new_files(path, new_paths)
            if snapshots:
                patch += self._new_file_patch(snapshots)
                # Detect mutation or replacement across Git generation, including
                # file modes and newly appearing files. Never emit a mixed snapshot.
                if snapshots != _snapshot_new_files(
                    path, new_paths
                ) or untracked != self._run_bytes(
                    ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=path
                ):
                    raise _unsafe_patch()
            if len(patch) > _MAX_PATCH_BYTES:
                raise _unsafe_patch()
            if b"\nGIT binary patch\n" in patch or b"\x00" in patch:
                raise _unsafe_patch()
            if any(
                line.startswith((b"new mode ", b"new file mode "))
                and line.rsplit(b" ", 1)[-1] not in {b"100644", b"100755"}
                for line in patch.splitlines()
            ):
                raise _unsafe_patch()
            actual_paths = (
                _parse_numstat_paths(
                    self._run_bytes(
                        ["git", "apply", "--numstat", "-z", "-"], cwd=path, input_bytes=patch
                    )
                )
                if patch
                else []
            )
            if (
                actual_paths != sorted(set(changed_paths + new_paths))
                or tracked_snapshots != _snapshot_new_files(path, existing_changed)
                or entries != self._run_bytes(["git", "ls-files", "--stage", "-z"], cwd=path)
            ):
                raise _unsafe_patch()
            content = patch.decode("utf-8", errors="strict")
        except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
            invalid = True
        if invalid:
            raise _unsafe_patch()
        return PatchInfo(
            content=content,
            sha256=sha256_bytes(patch),
            changed_paths=actual_paths,
        )

    def _new_file_patch(self, snapshots: list[tuple[str, str, bytes]]) -> bytes:
        # Only this private, disposable repository receives objects or index
        # changes. No candidate filters, attributes, index or object DB are used.
        with TemporaryDirectory(prefix="patch-", dir=self.state_root) as directory:
            scratch = Path(directory)
            self._run(["git", "init", "--template=", "--initial-branch=patch"], cwd=scratch)
            for logical_path, mode, content in snapshots:
                object_id = (
                    self._run_bytes(
                        ["git", "hash-object", "--no-filters", "-w", "--stdin"],
                        cwd=scratch,
                        input_bytes=content,
                    )
                    .decode("ascii")
                    .strip()
                )
                if _OBJECT_ID.fullmatch(object_id) is None:
                    raise _unsafe_patch()
                self._run(
                    [
                        "git",
                        "update-index",
                        "--add",
                        "--cacheinfo",
                        f"{mode},{object_id},{logical_path}",
                    ],
                    cwd=scratch,
                )
            return self._run_bytes(
                [
                    "git",
                    "diff",
                    "--cached",
                    "--binary",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--src-prefix=a/",
                    "--dst-prefix=b/",
                ],
                cwd=scratch,
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
        registered = self._workspace_is_registered(repository_root, path)
        if not path.exists() and not registered:
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
        if path.exists() or self._workspace_is_registered(repository_root, path):
            raise FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "The exact Fleet worktree or its Git registration remains after cleanup.",
                "Keep its lease outstanding and retry exact-run recovery after inspection.",
            )

    def _workspace_is_registered(self, repository_root: Path, path: Path) -> bool:
        listing = self._run_bytes(
            ["git", "worktree", "list", "--porcelain", "-z"],
            cwd=repository_root.resolve(strict=True),
        )
        expected = b"worktree " + os.fsencode(path)
        return expected in listing.split(b"\x00")

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
        (target / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
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
                ".gitignore",
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
        (target / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n", encoding="utf-8")
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
                ".gitignore",
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


def _snapshot_new_files(root: Path, logical_paths: list[str]) -> list[tuple[str, str, bytes]]:
    snapshots: list[tuple[str, str, bytes]] = []
    total = 0
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for logical_path in logical_paths:
            parts = logical_path.split("/")
            _validate_patch_path(logical_path)
            parent_fd = os.dup(root_fd)
            try:
                for part in parts[:-1]:
                    _check_patch_case(parent_fd, part)
                    child_fd = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd
                    )
                    os.close(parent_fd)
                    parent_fd = child_fd
                    if any(name.casefold() == ".git" for name in os.listdir(parent_fd)):
                        raise _unsafe_patch()
                _check_patch_case(parent_fd, parts[-1])
                descriptor = os.open(
                    parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd
                )
                try:
                    before = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_nlink != 1
                        or before.st_size > _MAX_NEW_FILE_BYTES
                        or before.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)
                    ):
                        raise _unsafe_patch()
                    chunks: list[bytes] = []
                    size = 0
                    while chunk := os.read(descriptor, min(65536, _MAX_NEW_FILE_BYTES + 1 - size)):
                        chunks.append(chunk)
                        size += len(chunk)
                        if size > _MAX_NEW_FILE_BYTES:
                            raise _unsafe_patch()
                    after = os.fstat(descriptor)
                    current = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
                    if (
                        _file_identity(before) != _file_identity(after)
                        or _file_identity(after) != _file_identity(current)
                        or size != after.st_size
                    ):
                        raise _unsafe_patch()
                    total += size
                    if total > _MAX_NEW_FILES_BYTES:
                        raise _unsafe_patch()
                    mode = "100755" if before.st_mode & stat.S_IXUSR else "100644"
                    content = b"".join(chunks)
                    _validate_text_patch_content(content)
                    snapshots.append((logical_path, mode, content))
                finally:
                    os.close(descriptor)
            finally:
                os.close(parent_fd)
    finally:
        os.close(root_fd)
    return snapshots


def _reject_special_files(root: Path, gitlinks: set[str]) -> None:
    # Git omits FIFOs/sockets/device nodes from both ls-files and status. They
    # must not become invisible verifier mutations, even when Git ignores them.
    visited = 0

    def visit(descriptor: int, prefix: str, depth: int) -> None:
        nonlocal visited
        if depth > 64:
            raise _unsafe_patch()
        for name in os.listdir(descriptor):
            if name.casefold() == ".git":
                continue
            visited += 1
            if visited > 100_000:
                raise _unsafe_patch()
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            logical_path = prefix + name
            if stat.S_ISDIR(info.st_mode):
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                try:
                    if logical_path in gitlinks and os.listdir(child):
                        raise _unsafe_patch()
                    visit(child, logical_path + "/", depth + 1)
                finally:
                    os.close(child)
            elif not stat.S_ISREG(info.st_mode) and not stat.S_ISLNK(info.st_mode):
                raise _unsafe_patch()

    invalid = False
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            visit(descriptor, "", 0)
        finally:
            os.close(descriptor)
    except OSError:
        invalid = True
    if invalid:
        raise _unsafe_patch()


def _file_identity(info: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_mtime_ns, info.st_ctime_ns


def _validate_patch_path(logical_path: str) -> None:
    parts = logical_path.split("/")
    if (
        not path_is_within(logical_path, (".",))
        or any(part.casefold() in _PROTECTED_PATCH_COMPONENTS for part in parts)
        or parts[-1].casefold() in _PROTECTED_PATCH_LEAVES
    ):
        raise _unsafe_patch()


def _validate_text_patch_content(content: bytes) -> None:
    invalid = False
    try:
        if b"\x00" in content:
            raise _unsafe_patch()
        content.decode("utf-8", errors="strict")
    except UnicodeError:
        invalid = True
    if invalid:
        raise _unsafe_patch()


def _check_patch_case(parent_fd: int, name: str) -> None:
    if [entry for entry in os.listdir(parent_fd) if entry.casefold() == name.casefold()] != [name]:
        raise _unsafe_patch()


def _unsafe_patch() -> FleetError:
    return FleetError(
        ErrorCode.ARTIFACT_INTEGRITY_FAILED,
        "Candidate contains an unsafe, changed, binary, unbounded, or noncanonical patch input.",
        "Use bounded UTF-8 regular text files in scope and leave the Git index unchanged.",
    )


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
        "diff.autoRefreshIndex=false",
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
