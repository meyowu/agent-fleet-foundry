from __future__ import annotations

import json
import multiprocessing
import os
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_fleet.adapters.trust.filesystem import FilesystemTrustStore
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.models import CanonicalResource, WorkflowStage, WorkspaceKind
from agent_fleet.domain.security import Redactor
from agent_fleet.domain.trust import (
    ExactPermissionScope,
    ProjectTrustSettings,
    TrustMode,
    UserTrustPolicy,
    UserTrustRule,
)
from agent_fleet.ports.trust_store import TrustStore


def policy(*, content: str = "safe content") -> UserTrustPolicy:
    scope = ExactPermissionScope(
        project_id="prj_" + "1" * 32,
        repository_identity="a" * 64,
        principal_role="engineer",
        workflow="code-change",
        stage=WorkflowStage.IMPLEMENTING,
        action="workspace.write_file",
        resource=CanonicalResource(kind="workspace_path", identifier="src/main.py"),
        parameters={"content": content},
        workspace_kind=WorkspaceKind.CANDIDATE,
        sandbox_provider="docker",
        sandbox_security_level="isolated",
        network_mode="none",
    )
    return UserTrustPolicy(
        projects=[
            ProjectTrustSettings(
                project_id=scope.project_id,
                repository_identity=scope.repository_identity,
                trust_mode=TrustMode.SAFE,
                allowed_paths=("src",),
            )
        ],
        rules=[
            UserTrustRule(
                rule_id="rule_" + "1" * 32,
                scope=scope,
                effect="allow",
                created_at=datetime(2026, 9, 5, tzinfo=UTC),
            )
        ],
    )


def _write_private(path: Path, content: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)


def test_trust_store_is_lazy_and_save_reopens_with_private_files(tmp_path: Path) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    store: TrustStore = FilesystemTrustStore(path, Redactor())
    assert store.load() == UserTrustPolicy()
    assert not path.parent.exists()
    saved = store.save(policy(), expected_revision=0)
    assert saved.revision == 1
    assert policy().revision == 0
    assert FilesystemTrustStore(path, Redactor()).load() == saved
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o600 for item in path.parent.iterdir())


def test_revision_cas_preserves_current_policy_and_prior_validated_backup(tmp_path: Path) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    store = FilesystemTrustStore(path, Redactor())
    first = store.save(policy(), expected_revision=0)
    second = store.save(first.model_copy(update={"rules": []}), expected_revision=1)
    assert second.revision == 2 and not second.rules
    backup = path.with_name(path.name + ".revision-00000000000000000001.json")
    assert FilesystemTrustStore(backup, Redactor()).load() == first
    with pytest.raises(FleetError) as captured:
        store.save(first, expected_revision=1)
    assert captured.value.code is ErrorCode.APPROVAL_INVALID
    assert store.load() == second


@pytest.mark.parametrize(
    "unsafe",
    [
        "file-symlink",
        "parent-symlink",
        "hardlink",
        "fifo",
        "file-mode",
        "parent-mode",
        "lock-hardlink",
    ],
)
def test_unsafe_storage_never_acquires_authority(tmp_path: Path, unsafe: str) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    store = FilesystemTrustStore(path, Redactor())
    saved = store.save(policy(), expected_revision=0)
    outside = tmp_path / "outside"
    if unsafe == "file-symlink":
        path.rename(outside)
        path.symlink_to(outside)
    elif unsafe == "parent-symlink":
        path.parent.rename(outside)
        path.parent.symlink_to(outside, target_is_directory=True)
    elif unsafe == "hardlink":
        os.link(path, outside)
    elif unsafe == "fifo":
        path.unlink()
        os.mkfifo(path, 0o600)
    elif unsafe == "file-mode":
        path.chmod(0o644)
    elif unsafe == "parent-mode":
        path.parent.chmod(0o770)
    else:
        os.link(path.parent / ".trust.yaml.lock", outside)
    with pytest.raises(FleetError) as captured:
        if unsafe == "lock-hardlink":
            store.save(saved, expected_revision=1)
        else:
            store.load()
    assert captured.value.code is ErrorCode.STATE_UNAVAILABLE


@pytest.mark.parametrize(
    "content",
    [
        "revision: 0\nrevision: 1\n",
        "projects: &a []\nrules: *a\n",
        "!!python/object/apply:os.system ['false']",
        '{"revision": -1}',
        '{"revision": 0, "unknown": true}',
        '{"revision": 0, "rules": [',
        "[]",
        "x" * 2_000_001,
    ],
)
def test_corrupt_or_ambiguous_policy_is_never_treated_as_absent(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    _write_private(path, content)
    store = FilesystemTrustStore(path, Redactor())
    with pytest.raises(FleetError):
        store.load()
    with pytest.raises(FleetError):
        store.save(policy(), expected_revision=0)
    assert path.read_text() == content


def test_secret_rejection_is_cause_free_before_creation_or_during_read(tmp_path: Path) -> None:
    sentinel = "TRUST-REGISTERED-SECRET-12345"
    path = tmp_path / "policy" / "trust.yaml"
    store = FilesystemTrustStore(path, Redactor([sentinel]))
    with pytest.raises(FleetError) as captured:
        store.save(policy(content=sentinel), expected_revision=0)
    assert not path.parent.exists()
    assert sentinel not in str(captured.value) and captured.value.__cause__ is None
    _write_private(path, policy(content=sentinel).model_dump_json())
    with pytest.raises(FleetError) as read_error:
        store.load()
    assert sentinel not in str(read_error.value) and read_error.value.__cause__ is None


def test_unchecked_nested_policy_mutation_is_revalidated_before_write(tmp_path: Path) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    candidate = policy()
    candidate.rules[0].scope.resource.identifier = "../outside"
    with pytest.raises(FleetError):
        FilesystemTrustStore(path, Redactor()).save(candidate, expected_revision=0)
    assert not path.parent.exists()


def test_failed_publication_retains_effective_policy_and_valid_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    store = FilesystemTrustStore(path, Redactor())
    first = store.save(policy(), expected_revision=0)
    original_replace = os.replace

    def fail_policy_replace(src: str, dst: str, **kwargs: Any) -> None:
        if dst == "trust.yaml":
            raise OSError("simulated interrupted publication")
        original_replace(src, dst, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_policy_replace)
        with pytest.raises(FleetError):
            store.save(first.model_copy(update={"rules": []}), expected_revision=1)
    assert store.load() == first
    backup = path.with_name(path.name + ".revision-00000000000000000001.json")
    assert FilesystemTrustStore(backup, Redactor()).load() == first
    assert not list(path.parent.glob("*.tmp"))
    assert store.save(first, expected_revision=1).revision == 2


def test_corrupt_existing_revision_backup_blocks_update_without_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    store = FilesystemTrustStore(path, Redactor())
    first = store.save(policy(), expected_revision=0)
    backup = path.with_name(path.name + ".revision-00000000000000000001.json")
    _write_private(backup, json.dumps({"revision": 900}))
    with pytest.raises(FleetError):
        store.save(first, expected_revision=1)
    assert store.load() == first
    assert json.loads(backup.read_text())["revision"] == 900


def _race_save(path: str, ready: Any, result: Any) -> None:
    ready.wait(10)
    try:
        saved = FilesystemTrustStore(Path(path), Redactor()).save(policy(), expected_revision=0)
        result.put(str(saved.revision))
    except FleetError as error:
        result.put(error.code.value)


def test_process_lock_and_revision_cas_prevent_lost_updates(tmp_path: Path) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    result = context.Queue()
    workers = [
        context.Process(target=_race_save, args=(str(path), ready, result)) for _ in range(2)
    ]
    try:
        for worker in workers:
            worker.start()
        ready.set()
        outcomes = sorted(result.get(timeout=15) for _ in workers)
        for worker in workers:
            worker.join(timeout=15)
            assert worker.exitcode == 0
        assert outcomes == ["1", "APPROVAL_INVALID"]
        assert FilesystemTrustStore(path, Redactor()).load().revision == 1
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)
        result.close()


def test_competing_lock_creator_is_reopened_without_replacing_its_inode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    original_open = os.open
    injected = False
    created_inode: int | None = None

    def competing_open(name: str, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        nonlocal injected, created_inode
        if name == ".trust.yaml.lock" and flags & os.O_EXCL and not injected:
            injected = True
            competing = original_open(name, flags, mode, **kwargs)
            created_inode = os.fstat(competing).st_ino
            os.close(competing)
            raise FileExistsError("a competing writer created the same lock")
        return original_open(name, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", competing_open)
    saved = FilesystemTrustStore(path, Redactor()).save(policy(), expected_revision=0)
    assert saved.revision == 1 and injected
    assert (path.parent / ".trust.yaml.lock").stat().st_ino == created_inode


def test_parent_replacement_before_publication_does_not_write_outside_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "policy" / "trust.yaml"
    store = FilesystemTrustStore(path, Redactor())
    first = store.save(policy(), expected_revision=0)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    displaced = tmp_path / "displaced"
    original_check = store._check_directory
    swapped = False

    def replace_parent(descriptor: int) -> None:
        nonlocal swapped
        if not swapped and list(path.parent.glob("*.tmp")):
            swapped = True
            path.parent.rename(displaced)
            path.parent.symlink_to(outside, target_is_directory=True)
        original_check(descriptor)

    monkeypatch.setattr(store, "_check_directory", replace_parent)
    with pytest.raises(FleetError):
        store.save(first, expected_revision=1)
    assert swapped and list(outside.iterdir()) == []
    assert FilesystemTrustStore(displaced / "trust.yaml", Redactor()).load() == first
