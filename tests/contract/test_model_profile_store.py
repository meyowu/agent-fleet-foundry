"""Real SQLite mutation, revision, corruption and immutable recovery contracts."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from model_profiles_fixtures import ProfileHarness, make_profile_harness

from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.model_profiles import ModelProfile, ProjectModelSelection
from agent_fleet.domain.models import RuntimeConfiguration
from agent_fleet.domain.security import canonical_json_hash


@pytest.fixture
def harness(tmp_path: Path) -> ProfileHarness:
    return make_profile_harness(tmp_path)


def test_store_reopens_versions_and_atomic_audit(harness: ProfileHarness) -> None:
    first = harness.add("coding")
    second = ModelProfile(
        name="coding", revision=2, enabled=False, configuration=RuntimeConfiguration(max_requests=3)
    )
    harness.store.save_profile(second, expected_revision=1)
    reopened = harness.reopen()
    assert reopened.get_profile("coding") == second
    assert reopened.list_profiles() == (second,)
    assert reopened.profile_revision("coding") == 2
    audit = reopened.list_audit()
    assert [item.action for item in audit] == ["profile.set", "profile.set"]
    assert [item.revision for item in audit] == [1, 2]
    assert audit[1].previous_sha256 == audit[0].audit_sha256
    assert audit[0].record_sha256 == canonical_json_hash(first.model_dump(mode="json"))
    with sqlite3.connect(harness.state.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM model_profile_versions").fetchone()[0] == 2


def test_stale_revision_and_recreation_cannot_aba(harness: ProfileHarness) -> None:
    first = harness.add("coding")
    with pytest.raises(FleetError):
        harness.store.save_profile(first, expected_revision=0)
    assert harness.store.remove_profile("coding", expected_revision=1) == 2
    assert harness.store.get_profile("coding") is None
    assert harness.store.profile_revision("coding") == 2
    with pytest.raises(FleetError):
        harness.store.save_profile(first, expected_revision=0)
    replacement = first.model_copy(update={"revision": 3})
    harness.store.save_profile(replacement, expected_revision=2)
    assert harness.reopen().get_profile("coding") == replacement
    assert [item.action for item in harness.store.list_audit()] == [
        "profile.set",
        "profile.remove",
        "profile.set",
    ]


def test_concurrent_profile_update_has_one_winner(harness: ProfileHarness) -> None:
    harness.add("coding")
    barrier = Barrier(2)

    def update(requests: int) -> bool:
        barrier.wait()
        try:
            harness.reopen().save_profile(
                ModelProfile(
                    name="coding",
                    revision=2,
                    configuration=RuntimeConfiguration(max_requests=requests),
                ),
                expected_revision=1,
            )
            return True
        except FleetError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(update, [3, 5]))
    assert sorted(results) == [False, True]
    assert len(harness.store.list_audit()) == 2
    assert harness.store.profile_revision("coding") == 2


def test_profile_write_failure_rolls_back_its_audit(harness: ProfileHarness) -> None:
    with sqlite3.connect(harness.state.database_path) as connection:
        connection.execute(
            "CREATE TRIGGER deny_profile BEFORE INSERT ON model_profile_versions "
            "BEGIN SELECT RAISE(ABORT, 'fixture'); END"
        )
    with pytest.raises(FleetError) as caught:
        harness.add("coding")
    assert caught.value.code is ErrorCode.STATE_UNAVAILABLE
    assert harness.store.list_audit() == ()
    assert harness.store.list_profiles() == ()


def test_active_selection_blocks_remove_but_revoke_preserves_snapshot(
    harness: ProfileHarness,
) -> None:
    harness.add("coding")
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    bindings = harness.resolve()
    harness.store.save_bindings(bindings)
    with pytest.raises(FleetError):
        harness.store.remove_profile("coding", expected_revision=1)
    harness.service.bind(
        harness.project, default=True, clear=True, revoke=("coding",), expected_revision=1
    )
    assert harness.store.remove_profile("coding", expected_revision=1) == 2
    assert (
        harness.reopen().get_bindings(harness.project.project_id, bindings.root_run_id) == bindings
    )
    assert (
        harness.service.for_run(
            harness.project,
            root_run_id=bindings.root_run_id,
            expected_sha256=bindings.bindings_sha256,
            required_roles=("cos", "engineer"),
        )
        == bindings
    )
    with pytest.raises(FleetError):
        harness.resolve()


def test_disabled_profile_is_not_absent_and_prevents_new_resolution(
    harness: ProfileHarness,
) -> None:
    first = harness.add("coding")
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    snapshot = harness.resolve()
    harness.store.save_bindings(snapshot)
    harness.store.save_profile(
        first.model_copy(update={"revision": 2, "enabled": False}), expected_revision=1
    )
    assert harness.store.get_profile("coding") is not None
    with pytest.raises(FleetError):
        harness.resolve()
    assert harness.store.get_bindings(harness.project.project_id, snapshot.root_run_id) == snapshot


@pytest.mark.parametrize("change", ["profile", "selection"])
def test_resolution_publication_cas_rejects_changed_review(
    harness: ProfileHarness, change: str
) -> None:
    first = harness.add("coding")
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    snapshot = harness.resolve()
    if change == "profile":
        harness.store.save_profile(first.model_copy(update={"revision": 2}), expected_revision=1)
    else:
        harness.service.bind(
            harness.project, profile="coding", role="engineer", expected_revision=1
        )
    with pytest.raises(FleetError):
        harness.store.save_bindings(snapshot)
    assert harness.store.get_bindings(harness.project.project_id, snapshot.root_run_id) is None
    assert not any(item.action == "run.bind" for item in harness.store.list_audit())


def test_immutable_binding_replay_is_idempotent_and_retarget_denied(
    harness: ProfileHarness,
) -> None:
    snapshot = harness.resolve()
    harness.store.save_bindings(snapshot)
    harness.store.save_bindings(snapshot)
    assert len(harness.store.list_audit()) == 1
    with pytest.raises(FleetError):
        harness.store.save_bindings(
            snapshot.model_copy(update={"roles": {"cos": snapshot.roles["cos"]}})
        )
    with pytest.raises(FleetError):
        harness.store.get_bindings("prj_" + "f" * 32, snapshot.root_run_id)


@pytest.mark.parametrize(
    "table,column,where",
    [
        ("model_profile_versions", "record_sha256", "name='coding'"),
        ("model_configuration_audit", "audit_sha256", "sequence=1"),
        ("model_profile_versions", "data_json", "name='coding'"),
    ],
)
def test_profile_corrupt_hash_or_json_fails_closed(
    harness: ProfileHarness, table: str, column: str, where: str
) -> None:
    harness.add("coding")
    with sqlite3.connect(harness.state.database_path) as connection:
        connection.execute(f"UPDATE {table} SET {column}=? WHERE {where}", ("corrupt",))
    with pytest.raises(FleetError) as caught:
        harness.store.get_profile("coding")
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_deleted_or_rolled_back_profile_head_is_not_absence(harness: ProfileHarness) -> None:
    first = harness.add("coding")
    harness.store.save_profile(first.model_copy(update={"revision": 2}), expected_revision=1)
    with sqlite3.connect(harness.state.database_path) as connection:
        connection.execute("UPDATE model_profile_heads SET revision=1")
    with pytest.raises(FleetError):
        harness.store.get_profile("coding")
    with sqlite3.connect(harness.state.database_path) as connection:
        connection.execute("DELETE FROM model_profile_heads")
    with pytest.raises(FleetError):
        harness.store.list_profiles()


@pytest.mark.parametrize("change", ["identity", "hash", "deleted_head"])
def test_selection_tampering_does_not_enable_legacy_fallback(
    harness: ProfileHarness, change: str
) -> None:
    harness.add("coding")
    harness.service.bind(harness.project, profile="coding", default=True, expected_revision=0)
    with sqlite3.connect(harness.state.database_path) as connection:
        if change == "deleted_head":
            connection.execute("DELETE FROM project_model_selection_heads")
        elif change == "hash":
            connection.execute(
                "UPDATE project_model_selection_versions SET record_sha256=?", ("0" * 64,)
            )
        else:
            raw = connection.execute(
                "SELECT data_json FROM project_model_selection_versions"
            ).fetchone()[0]
            data = json.loads(raw)
            data["repository_identity"] = "0" * 64
            connection.execute(
                "UPDATE project_model_selection_versions SET data_json=?", (json.dumps(data),)
            )
    with pytest.raises(FleetError):
        harness.resolve()


def test_rejected_invalid_selection_has_no_audit_or_state(harness: ProfileHarness) -> None:
    harness.add("coding")
    selection = ProjectModelSelection(
        project_id=harness.project.project_id,
        repository_identity="f" * 64,
        revision=1,
        default_profile="coding",
        permitted_profiles=("coding",),
    )
    with pytest.raises(FleetError):
        harness.store.save_selection(selection, expected_revision=0)
    assert harness.store.get_selection(harness.project.project_id) is None
    assert len(harness.store.list_audit()) == 1


def test_missing_required_snapshot_never_uses_legacy(harness: ProfileHarness) -> None:
    run = harness.run()
    with pytest.raises(FleetError) as caught:
        harness.service.for_run(
            harness.project,
            root_run_id=run.run_id,
            expected_sha256="1" * 64,
            required_roles=("cos",),
        )
    assert caught.value.code is ErrorCode.RECOVERY_REQUIRED


def test_bindings_corruption_is_denied_even_with_updated_record_hash(
    harness: ProfileHarness,
) -> None:
    snapshot = harness.resolve()
    harness.store.save_bindings(snapshot)
    with sqlite3.connect(harness.state.database_path) as connection:
        data = json.loads(snapshot.model_dump_json())
        data["roles"]["cos"]["configuration"]["max_requests"] = 2
        data["roles"]["cos"]["configuration_sha256"] = canonical_json_hash(
            data["roles"]["cos"]["configuration"]
        )
        connection.execute(
            "UPDATE run_model_bindings SET data_json=?, bindings_sha256=?",
            (json.dumps(data), canonical_json_hash(data)),
        )
    with pytest.raises(FleetError):
        harness.reopen().get_bindings(harness.project.project_id, snapshot.root_run_id)


def test_registered_secret_never_enters_profile_rows_or_audit(harness: ProfileHarness) -> None:
    sentinel = "secret_model_name"
    harness.state.redactor.register_secret(sentinel)
    with pytest.raises(FleetError) as caught:
        harness.add(sentinel)
    assert sentinel not in str(caught.value)
    assert caught.value.__context__ is None
    assert harness.store.list_audit() == ()
    assert sentinel.encode() not in harness.state.database_path.read_bytes()


def test_read_without_migration_does_not_create_database(tmp_path: Path) -> None:
    harness = make_profile_harness(tmp_path)
    absent = tmp_path / "absent" / "state.db"
    harness.state.database_path = absent
    with pytest.raises(FleetError):
        harness.store.list_profiles()
    assert not absent.exists()


def test_migration9_preserves_existing_project_bytes(harness: ProfileHarness) -> None:
    with sqlite3.connect(harness.state.database_path) as connection:
        expected = connection.execute("SELECT data_json FROM projects").fetchone()[0]
        for table in (
            "plan_review_heads",
            "plan_review_versions",
            "run_model_bindings",
            "project_model_selection_heads",
            "project_model_selection_versions",
            "model_profile_heads",
            "model_profile_versions",
            "model_configuration_audit",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version>=9")
    assert harness.state.migrate() == 10
    with sqlite3.connect(harness.state.database_path) as connection:
        assert connection.execute("SELECT data_json FROM projects").fetchone()[0] == expected
        assert connection.execute("SELECT COUNT(*) FROM model_profile_versions").fetchone()[0] == 0
