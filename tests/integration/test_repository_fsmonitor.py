from __future__ import annotations

import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_fleet.adapters.repository.git import GitRepositoryAdapter
from agent_fleet.adapters.system import UuidIdGenerator
from agent_fleet.bootstrap import build_container
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import WorkspaceKind


def _repository_with_malicious_fsmonitor(tmp_path: Path) -> tuple[Path, Path]:
    fixture_root = tmp_path / "fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    sentinel = tmp_path / "fsmonitor-executed"
    hook = repository / ".git" / "hooks" / "malicious-fsmonitor"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)
    subprocess.run(
        ["git", "config", "--local", "core.fsmonitor", str(hook)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    configured = subprocess.run(
        ["git", "config", "--local", "--get", "core.fsmonitor"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert configured.stdout.strip() == str(hook)
    assert not sentinel.exists()
    return repository, sentinel


def _configure_malicious_clean_filter(repository: Path, sentinel: Path) -> None:
    attributes = repository / ".gitattributes"
    filtered = repository / "filtered.txt"
    attributes.write_text("filtered.txt filter=sentinel\n", encoding="utf-8")
    filtered.write_text("baseline\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitattributes", "filtered.txt"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Agent Fleet Test",
            "-c",
            "user.email=agent-fleet@example.invalid",
            "commit",
            "-m",
            "add filtered fixture",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    driver = repository / ".git" / "hooks" / "malicious-clean-filter"
    driver.parent.mkdir(parents=True, exist_ok=True)
    driver.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed\\n', encoding='utf-8')\n"
        "sys.stdout.buffer.write(sys.stdin.buffer.read())\n",
        encoding="utf-8",
    )
    driver.chmod(0o755)
    subprocess.run(
        ["git", "config", "--local", "filter.sentinel.clean", str(driver)],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    configured = subprocess.run(
        ["git", "config", "--local", "--get", "filter.sentinel.clean"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert configured.stdout.strip() == str(driver)
    assert not sentinel.exists()


def _commit_attributed_driver_fixture(
    repository: Path,
    *,
    attribute: str,
    filename: str,
) -> None:
    (repository / ".gitattributes").write_text(
        f"{filename} {attribute}\n",
        encoding="utf-8",
    )
    (repository / filename).write_text("baseline\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", ".gitattributes", filename],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Agent Fleet Test",
            "-c",
            "user.email=agent-fleet@example.invalid",
            "commit",
            "-m",
            "add adversarial driver fixture",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def _sentinel_program(repository: Path, sentinel: Path, name: str) -> Path:
    driver = repository / ".git" / "hooks" / name
    driver.parent.mkdir(parents=True, exist_ok=True)
    driver.write_text(
        f"#!{sys.executable}\n"
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed\\n', encoding='utf-8')\n",
        encoding="utf-8",
    )
    driver.chmod(0o755)
    return driver


def _set_and_confirm_local_config(repository: Path, key: str, value: str) -> None:
    subprocess.run(
        ["git", "config", "--local", key, value],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    configured = subprocess.run(
        ["git", "config", "--local", "--get", key],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    assert configured.stdout.strip() == value


@pytest.mark.integration
def test_git_inspect_does_not_execute_repository_local_fsmonitor(tmp_path: Path) -> None:
    repository, sentinel = _repository_with_malicious_fsmonitor(tmp_path)
    adapter = GitRepositoryAdapter(tmp_path / "adapter-state", UuidIdGenerator())

    inspected = adapter.inspect(repository)

    assert inspected.root == str(repository.resolve())
    assert not sentinel.exists()


@pytest.mark.integration
def test_project_preview_and_initialize_do_not_execute_repository_local_fsmonitor(
    tmp_path: Path,
) -> None:
    repository, sentinel = _repository_with_malicious_fsmonitor(tmp_path)
    container = build_container(tmp_path / "fleet-state")

    preview = container.projects.preview(repository)
    assert preview["repository"] == str(repository.resolve())
    assert not sentinel.exists()

    initialized = container.projects.initialize(
        repository,
        runtime_name="fake",
        sandbox_name="fake",
    )
    assert initialized["repository"] == str(repository.resolve())
    assert not sentinel.exists()


@pytest.mark.integration
def test_git_resolution_rejects_repository_sibling_path_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_root = tmp_path / "path-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    subdirectory = repository / "subdirectory"
    subdirectory.mkdir()
    repository_bin = repository / "bin"
    repository_bin.mkdir()
    sentinel = tmp_path / "path-git-executed"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git = repository_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{repository_bin}{os.pathsep}{os.environ['PATH']}")

    inspected = GitRepositoryAdapter(tmp_path / "path-adapter-state", UuidIdGenerator()).inspect(
        subdirectory
    )

    assert inspected.root == str(repository.resolve())
    assert not sentinel.exists()


@pytest.mark.integration
def test_git_resolution_preserves_lexical_symlink_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_state = tmp_path / "symlink-setup-state"
    repository = GitRepositoryAdapter(setup_state, UuidIdGenerator()).create_canary_fixture(
        setup_state / "repository"
    )
    canonical_parent = tmp_path / "canonical-parent"
    canonical_parent.mkdir()
    lexical_parent = tmp_path / "lexical-parent"
    lexical_parent.symlink_to(canonical_parent, target_is_directory=True)
    controlled = canonical_parent / "controlled-alias"
    (controlled / ".git").mkdir(parents=True)
    controlled_bin = controlled / "bin"
    controlled_bin.mkdir()
    (controlled / "linked-repository").symlink_to(repository, target_is_directory=True)
    linked_repository = lexical_parent / "controlled-alias" / "linked-repository"
    sentinel = tmp_path / "symlink-git-executed"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git = controlled_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{controlled_bin}{os.pathsep}{os.environ['PATH']}")

    inspected = GitRepositoryAdapter(tmp_path / "symlink-adapter-state", UuidIdGenerator()).inspect(
        linked_repository
    )

    assert inspected.root == str(repository.resolve())
    assert not sentinel.exists()


@pytest.mark.integration
def test_git_resolution_rejects_differently_cased_repository_path_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual_parent = tmp_path / "CaseSensitiveProbe"
    actual_parent.mkdir()
    alternate_parent = tmp_path / "casesensitiveprobe"
    if not alternate_parent.exists() or not os.path.samefile(actual_parent, alternate_parent):
        pytest.skip("filesystem is case-sensitive")
    repository = GitRepositoryAdapter(actual_parent, UuidIdGenerator()).create_canary_fixture(
        actual_parent / "Repository"
    )
    alternate_repository = alternate_parent / "repository"
    assert alternate_repository.exists()
    assert os.path.samefile(repository, alternate_repository)
    malicious_bin = alternate_repository / "BiN"
    malicious_bin.mkdir()
    sentinel = tmp_path / "case-folded-git-executed"
    real_git = shutil.which("git")
    assert real_git is not None
    fake_git = malicious_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{malicious_bin}{os.pathsep}{os.environ['PATH']}")

    inspected = GitRepositoryAdapter(tmp_path / "case-adapter-state", UuidIdGenerator()).inspect(
        repository
    )

    assert inspected.root == str(repository.resolve())
    assert not sentinel.exists()


@pytest.mark.integration
def test_git_resolution_excludes_linked_worktree_metadata_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setup_state = tmp_path / "linked-setup-state"
    repository = GitRepositoryAdapter(setup_state, UuidIdGenerator()).create_canary_fixture(
        setup_state / "repository"
    )
    linked_worktree = tmp_path / "linked-worktree"
    real_git = shutil.which("git")
    assert real_git is not None
    subprocess.run(
        [real_git, "worktree", "add", "--detach", str(linked_worktree), "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    git_file = (linked_worktree / ".git").read_text(encoding="utf-8").strip()
    assert git_file.startswith("gitdir: ")
    linked_git_dir = Path(git_file.removeprefix("gitdir: "))
    malicious_bin = linked_git_dir / "bin"
    malicious_bin.mkdir()
    sentinel = tmp_path / "linked-metadata-git-executed"
    fake_git = malicious_bin / "git"
    fake_git.write_text(
        f"#!/bin/sh\ntouch '{sentinel}'\nexec '{real_git}' \"$@\"\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{malicious_bin}{os.pathsep}{os.environ['PATH']}")

    inspected = GitRepositoryAdapter(tmp_path / "linked-adapter-state", UuidIdGenerator()).inspect(
        linked_worktree
    )

    assert inspected.root == str(linked_worktree.resolve())
    assert not sentinel.exists()


@pytest.mark.integration
def test_repository_local_core_worktree_cannot_switch_project_boundary(tmp_path: Path) -> None:
    fixture_root = tmp_path / "identity-fixture-state"
    adapter = GitRepositoryAdapter(fixture_root, UuidIdGenerator())
    outer = adapter.create_canary_fixture(fixture_root / "outer")
    nested = adapter.create_canary_fixture(outer / "nested")
    subprocess.run(
        ["git", "config", "--local", "core.worktree", str(outer)],
        cwd=nested,
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(FleetError) as captured:
        adapter.inspect(nested)

    assert captured.value.code is ErrorCode.PROJECT_NOT_GIT
    assert not (outer / ".fleet").exists()

    container = build_container(tmp_path / "identity-app-state")
    with pytest.raises(FleetError) as init_error:
        container.projects.initialize(nested, runtime_name="fake", sandbox_name="fake")
    assert init_error.value.code is ErrorCode.PROJECT_NOT_GIT
    assert not (outer / ".fleet").exists()


@pytest.mark.integration
@pytest.mark.parametrize(
    "config_case",
    ["include", "include-if", "hook-command", "hook-event"],
)
def test_repository_config_with_indirect_execution_surface_fails_closed(
    tmp_path: Path,
    config_case: str,
) -> None:
    fixture_root = tmp_path / f"{config_case}-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    sentinel = tmp_path / f"{config_case}-executed"
    driver = _sentinel_program(repository, sentinel, f"malicious-{config_case}")
    if config_case in {"include", "include-if"}:
        included = tmp_path / f"{config_case}.config"
        included.write_text(f"[core]\n\tfsmonitor = {driver}\n", encoding="utf-8")
        key = "include.path" if config_case == "include" else f"includeIf.gitdir:{repository}/.path"
        value = str(included)
    else:
        key = f"hook.sentinel.{'command' if config_case == 'hook-command' else 'event'}"
        value = str(driver)
    _set_and_confirm_local_config(repository, key, value)

    with pytest.raises(FleetError) as captured:
        GitRepositoryAdapter(tmp_path / f"{config_case}-adapter-state", UuidIdGenerator()).inspect(
            repository
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not sentinel.exists()


@pytest.mark.integration
def test_missing_promisor_blob_cannot_trigger_repository_upload_pack(tmp_path: Path) -> None:
    fixture_root = tmp_path / "promisor-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    origin = tmp_path / "promisor-origin"
    shutil.copytree(repository, origin)
    blob_id = subprocess.run(
        ["git", "rev-parse", "HEAD:src/canary_calc/core.py"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    blob_path = repository / ".git" / "objects" / blob_id[:2] / blob_id[2:]
    assert blob_path.is_file()
    sentinel = tmp_path / "upload-pack-executed"
    upload_pack = _sentinel_program(repository, sentinel, "malicious-upload-pack")
    for key, value in (
        ("remote.origin.url", str(origin)),
        ("remote.origin.promisor", "true"),
        ("remote.origin.partialclonefilter", "blob:none"),
        ("remote.origin.uploadpack", str(upload_pack)),
        ("protocol.file.allow", "always"),
    ):
        _set_and_confirm_local_config(repository, key, value)
    blob_path.unlink()

    adapter = GitRepositoryAdapter(tmp_path / "promisor-adapter-state", UuidIdGenerator())
    with pytest.raises(FleetError) as captured:
        adapter.create_workspace(
            repository,
            "run_44444444444444444444444444444444",
            head,
            WorkspaceKind.CANDIDATE,
        )

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert not sentinel.exists()


@pytest.mark.integration
def test_repository_local_clean_filter_fails_closed_without_execution(tmp_path: Path) -> None:
    fixture_root = tmp_path / "filter-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    sentinel = tmp_path / "clean-filter-executed"
    _configure_malicious_clean_filter(repository, sentinel)
    adapter = GitRepositoryAdapter(tmp_path / "adapter-state", UuidIdGenerator())
    with pytest.raises(FleetError) as captured:
        adapter.inspect(repository)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not sentinel.exists()


@pytest.mark.integration
def test_repository_local_process_filter_fails_closed_without_execution(tmp_path: Path) -> None:
    fixture_root = tmp_path / "process-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    filename = "process-filtered.txt"
    _commit_attributed_driver_fixture(
        repository,
        attribute="filter=process-sentinel",
        filename=filename,
    )
    sentinel = tmp_path / "process-filter-executed"
    driver = _sentinel_program(repository, sentinel, "malicious-process-filter")
    _set_and_confirm_local_config(
        repository,
        "filter.process-sentinel.process",
        str(driver),
    )
    (repository / filename).write_text("changed\n", encoding="utf-8")
    assert not sentinel.exists()

    with pytest.raises(FleetError) as captured:
        GitRepositoryAdapter(
            tmp_path / "process-adapter-state",
            UuidIdGenerator(),
        ).inspect(repository)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not sentinel.exists()


@pytest.mark.integration
@pytest.mark.parametrize("config_field", ["textconv", "command"])
def test_repository_local_diff_driver_fails_closed_without_execution(
    tmp_path: Path,
    config_field: str,
) -> None:
    fixture_root = tmp_path / f"diff-{config_field}-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    filename = "diff-driven.txt"
    _commit_attributed_driver_fixture(
        repository,
        attribute="diff=sentinel",
        filename=filename,
    )
    sentinel = tmp_path / f"diff-{config_field}-executed"
    driver = _sentinel_program(repository, sentinel, f"malicious-{config_field}-driver")
    _set_and_confirm_local_config(
        repository,
        f"diff.sentinel.{config_field}",
        str(driver),
    )
    assert not sentinel.exists()
    adapter = GitRepositoryAdapter(
        tmp_path / f"diff-{config_field}-adapter-state", UuidIdGenerator()
    )
    with pytest.raises(FleetError) as captured:
        adapter.inspect(repository)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not sentinel.exists()


@pytest.mark.integration
def test_repository_driver_key_is_never_copied_into_secured_git_argv(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture_root = tmp_path / "driver-key-fixture-state"
    repository = GitRepositoryAdapter(fixture_root, UuidIdGenerator()).create_canary_fixture(
        fixture_root / "repository"
    )
    secret = "FLEET-GIT-ARGV-REGISTERED-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", secret)
    _set_and_confirm_local_config(
        repository,
        f"filter.{secret}.clean",
        "unused-command",
    )
    real_run = subprocess.run

    with (
        patch("agent_fleet.adapters.repository.git.subprocess.run", wraps=real_run) as run,
        pytest.raises(FleetError) as captured,
    ):
        GitRepositoryAdapter(
            tmp_path / "driver-key-adapter-state",
            UuidIdGenerator(),
        ).inspect(repository)

    child_argv = [call.args[0] for call in run.call_args_list if call.args]
    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert secret not in str(captured.value)
    assert all(secret not in str(argv) for argv in child_argv)


@pytest.mark.integration
def test_canonical_non_git_secret_path_is_not_exposed_before_repository_info(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "FLEET-CANONICAL-PATH-REGISTERED-SECRET"
    monkeypatch.setenv("AGENT_FLEET_REDACT_VALUES", secret)
    canonical = tmp_path / secret
    canonical.mkdir()
    safe_alias = tmp_path / "safe-alias"
    safe_alias.symlink_to(canonical, target_is_directory=True)
    state_root = tmp_path / "fleet-state"
    container = build_container(state_root, migrate=False)

    with pytest.raises(FleetError) as captured:
        container.projects.preview(safe_alias)

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.code is ErrorCode.PROJECT_NOT_GIT
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in str(captured.value)
    assert secret not in rendered
    assert not state_root.exists()
