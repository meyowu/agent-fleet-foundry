from __future__ import annotations

import copy
import os
import traceback
from pathlib import Path

import pytest
import yaml

from agent_fleet.adapters.config.yaml import (
    MAX_AGENT_GUIDANCE_BYTES,
    MAX_CONFIG_BYTES,
    MAX_CONFIG_SNAPSHOT_BYTES,
    YamlConfigurationAdapter,
    default_fleet_files,
    load_fleet_spec,
    parse_fleet_spec,
    parse_verification_profile,
    validate_fleet_files,
)
from agent_fleet.adapters.repository.profile import StaticRepositoryProfiler
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor


def test_default_fleet_spec_round_trips_strictly() -> None:
    files = default_fleet_files("canary-project")
    spec = validate_fleet_files(files)
    assert spec.spec.runtime.adapter == "fake"
    assert set(spec.spec.agents) == {"cos", "engineer", "verifier"}
    assert spec.spec.agents["cos"].allowed_tools == []
    assert spec.spec.agents["engineer"].allowed_tools == [
        "repo.list_files",
        "repo.read_file",
        "repo.search_text",
        "workspace.get_diff",
        "workspace.write_file",
        "workspace.apply_edit",
        "workspace.delete_path",
        "command.run",
        "fixture.record_side_effect",
    ]
    assert spec.spec.agents["verifier"].allowed_tools == [
        "repo.list_files",
        "repo.read_file",
        "repo.search_text",
        "workspace.get_diff",
        "command.run",
    ]


def test_pydantic_ai_fleet_spec_requires_and_preserves_opaque_provider_model() -> None:
    files = default_fleet_files(
        "provider-project",
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
    )

    spec = validate_fleet_files(files)

    assert spec.spec.runtime.adapter == "pydantic-ai"
    assert spec.spec.runtime.provider_model == "openai:gpt-5-mini"
    assert "credential" not in files["fleet.yaml"].casefold()


@pytest.mark.parametrize(
    ("runtime_name", "provider_model"),
    [
        ("pydantic-ai", None),
        ("fake", "openai:gpt-5-mini"),
        ("unknown", None),
    ],
)
def test_invalid_generated_runtime_selection_is_rejected(
    runtime_name: str, provider_model: str | None
) -> None:
    with pytest.raises(FleetError) as captured:
        default_fleet_files(
            "invalid-runtime",
            runtime_name=runtime_name,
            provider_model=provider_model,
        )

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_repository_fleet_spec_cannot_embed_a_credential_reference() -> None:
    files = default_fleet_files(
        "provider-project",
        runtime_name="pydantic-ai",
        provider_model="openai:gpt-5-mini",
    )
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["runtime"]["credentialRef"] = "env:OPENAI_API_KEY"
    files["fleet.yaml"] = yaml.safe_dump(data, sort_keys=False)

    with pytest.raises(FleetError) as captured:
        validate_fleet_files(files)

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_phase1_generated_role_labels_remain_loadable() -> None:
    files = default_fleet_files("existing-phase1-project")
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["agents"]["cos"]["role"] = "chief-of-staff"
    data["spec"]["agents"]["engineer"]["role"] = "software-engineer"
    data["spec"]["requestedPermissions"][0]["action"] = "workspace.write"
    files["fleet.yaml"] = yaml.safe_dump(data, sort_keys=False)

    spec = validate_fleet_files(files)

    assert spec.spec.agents["cos"].role == "chief-of-staff"
    assert spec.spec.agents["engineer"].role == "software-engineer"


def test_unrecognized_role_label_mismatch_is_rejected() -> None:
    files = default_fleet_files("invalid-role-project")
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["agents"]["engineer"]["role"] = "architect"
    files["fleet.yaml"] = yaml.safe_dump(data, sort_keys=False)

    with pytest.raises(FleetError, match="must match its role field"):
        validate_fleet_files(files)


@pytest.mark.parametrize(
    "content",
    [
        b"!!python/object/apply:os.system ['whoami']\n",
        b"base: &base {adapter: fake}\ncopy: *base\n",
        b"[]\n",
    ],
)
def test_unsafe_or_nonmapping_yaml_is_rejected(content: bytes) -> None:
    with pytest.raises(FleetError) as captured:
        parse_fleet_spec(content)
    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_registered_secret_is_rejected_before_yaml_parser_error_without_leak() -> None:
    secret = "FLEET-MALFORMED-YAML-REGISTERED-SECRET"
    adapter = YamlConfigurationAdapter(Redactor([secret]))

    with pytest.raises(FleetError, match="registered secret material") as captured:
        adapter.validate_files(
            {
                "fleet.yaml": f"apiVersion: [{secret}\n",
            }
        )

    rendered = "".join(traceback.format_exception(captured.value))
    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
    assert secret not in str(captured.value)
    assert secret not in rendered


def test_unknown_field_is_rejected() -> None:
    data = yaml.safe_load(default_fleet_files("canary")["fleet.yaml"])
    data["unexpected"] = True
    with pytest.raises(FleetError, match="extra_forbidden"):
        parse_fleet_spec(yaml.safe_dump(data).encode())


def test_deeply_nested_yaml_fails_with_typed_configuration_error() -> None:
    content = ("jobs: " + "[" * 650 + "0" + "]" * 650 + "\n").encode()

    with pytest.raises(FleetError) as captured:
        parse_fleet_spec(content)

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_reference_traversal_is_rejected() -> None:
    files = copy.deepcopy(default_fleet_files("canary"))
    data = yaml.safe_load(files["fleet.yaml"])
    data["spec"]["agents"]["engineer"]["instructions"] = "../outside.md"
    files["fleet.yaml"] = yaml.safe_dump(data)
    files["../outside.md"] = "untrusted"
    with pytest.raises(FleetError) as captured:
        validate_fleet_files(files)
    assert captured.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.parametrize(
    "unsafe_path", ["../escape", "/absolute", "./redundant", ".", "extra\x00name", "line\nbreak"]
)
def test_unreferenced_unsafe_output_path_is_rejected(unsafe_path: str) -> None:
    files = default_fleet_files("canary")
    files[unsafe_path] = "untrusted"

    with pytest.raises(FleetError) as captured:
        validate_fleet_files(files)

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_config_publish_never_overwrites_a_concurrent_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    files = adapter.default_files("concurrent-project")
    original_link = os.link
    raced = False

    def racing_link(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal raced
        if not raced:
            raced = True
            assert dst_dir_fd is not None
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dst_dir_fd,
            )
            try:
                os.write(descriptor, b"concurrent owner\n")
            finally:
                os.close(descriptor)
            raise FileExistsError(destination)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", racing_link)

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert raced is True
    assert (fleet_root / "fleet.yaml").read_text(encoding="utf-8") == "concurrent owner\n"


def test_config_publish_preserves_replacement_created_after_successful_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    files = adapter.default_files("post-link-race")
    original_link = os.link
    replaced = False

    def replacing_link(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal replaced
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        if destination == "fleet.yaml" and not replaced:
            replaced = True
            assert dst_dir_fd is not None
            os.unlink(destination, dir_fd=dst_dir_fd)
            descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=dst_dir_fd,
            )
            try:
                os.write(descriptor, b"concurrent replacement\n")
            finally:
                os.close(descriptor)

    monkeypatch.setattr(os, "link", replacing_link)

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert replaced is True
    assert (fleet_root / "fleet.yaml").read_text(encoding="utf-8") == ("concurrent replacement\n")


def test_config_publish_preserves_replaced_temporary_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    files = adapter.default_files("temporary-name-race")
    original_link = os.link
    replaced_name: str | None = None

    def replacing_source_name(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal replaced_name
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )
        if destination == "fleet.yaml" and replaced_name is None:
            assert isinstance(source, str)
            assert src_dir_fd is not None
            replaced_name = source
            os.unlink(source, dir_fd=src_dir_fd)
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=src_dir_fd,
            )
            try:
                os.write(descriptor, b"concurrent temporary owner\n")
            finally:
                os.close(descriptor)

    monkeypatch.setattr(os, "link", replacing_source_name)

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert replaced_name is not None
    assert not (fleet_root / "fleet.yaml").exists()
    assert (fleet_root / replaced_name).read_text(encoding="utf-8") == (
        "concurrent temporary owner\n"
    )


def test_config_publish_rolls_back_files_after_parent_directory_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    outside = tmp_path / "moved-agents"
    files = adapter.default_files("parent-race-project")
    original_link = os.link
    link_count = 0

    def swapping_link(
        source: str | os.PathLike[str],
        destination: str | os.PathLike[str],
        *,
        src_dir_fd: int | None = None,
        dst_dir_fd: int | None = None,
        follow_symlinks: bool = True,
    ) -> None:
        nonlocal link_count
        link_count += 1
        if link_count == 2:
            (fleet_root / "agents").rename(outside)
            (fleet_root / "agents").symlink_to(outside, target_is_directory=True)
        original_link(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
            follow_symlinks=follow_symlinks,
        )

    monkeypatch.setattr(os, "link", swapping_link)

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.RECOVERY_REQUIRED
    assert outside.is_dir()
    assert not any(path.is_file() for path in outside.rglob("*"))
    assert not (fleet_root / "fleet.yaml").exists()


def test_apply_rejects_oversized_candidate_before_publishing_any_file(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    files = adapter.default_files("oversized-candidate")
    files["agents/engineer.md"] = "x" * (MAX_CONFIG_BYTES + 1)

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not fleet_root.exists()


def test_apply_rejects_oversized_agent_guidance_before_publication(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    files = adapter.default_files("oversized-guidance")
    files["agents/engineer.md"] = "x" * (MAX_AGENT_GUIDANCE_BYTES + 1)

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not fleet_root.exists()


def test_apply_rejects_oversized_candidate_snapshot_before_publication(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    files = adapter.default_files("oversized-snapshot")
    file_count = (MAX_CONFIG_SNAPSHOT_BYTES // MAX_CONFIG_BYTES) + 1
    for index in range(file_count):
        files[f"extra/{index}.md"] = "x" * MAX_CONFIG_BYTES

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, files)

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert not fleet_root.exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is unavailable")
def test_apply_rejects_existing_fifo_without_opening_it(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    fleet_root.mkdir()
    os.mkfifo(fleet_root / "fleet.yaml")

    with pytest.raises(FleetError) as captured:
        adapter.apply(fleet_root, adapter.default_files("fifo-project"))

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_fleet_yaml_symlink_escape_is_rejected(tmp_path: Path) -> None:
    files = default_fleet_files("canary")
    outside = tmp_path / "outside.yaml"
    outside.write_text(files["fleet.yaml"], encoding="utf-8")
    fleet_root = tmp_path / ".fleet"
    fleet_root.mkdir()
    (fleet_root / "fleet.yaml").symlink_to(outside)
    with pytest.raises(FleetError) as captured:
        load_fleet_spec(fleet_root / "fleet.yaml")
    assert captured.value.code is ErrorCode.PATH_OUTSIDE_SCOPE


def test_profile_drives_repository_specific_verification_commands(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        '{"packageManager":"pnpm@9","scripts":{"test":"vitest run","build":"vite build"}}',
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9'\n", encoding="utf-8")
    profile = StaticRepositoryProfiler().profile(tmp_path).profile
    files = default_fleet_files("node-project", profile)
    verification = parse_verification_profile(files["project/verification.yaml"].encode())
    assert verification.commands["node-test"].executable == "pnpm"
    assert verification.commands["node-test"].argv == ["run", "test"]
    assert verification.commands["node-build"].argv == ["run", "build"]

    (tmp_path / "package.json").write_text(
        '{"packageManager":"pnpm@9","scripts":{"build":"vite build"}}',
        encoding="utf-8",
    )
    changed_profile = StaticRepositoryProfiler().profile(tmp_path).profile
    changed_files = default_fleet_files("node-project", changed_profile)
    changed_verification = parse_verification_profile(
        changed_files["project/verification.yaml"].encode()
    )
    assert "node-test" not in changed_verification.commands


def test_config_snapshot_hash_covers_every_referenced_file(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("snapshot-project"))
    _, initial = adapter.load_snapshot(fleet_root / "fleet.yaml")
    initial_hash = adapter.snapshot_hash(initial)

    verification = fleet_root / "project" / "verification.yaml"
    verification.write_text(
        verification.read_text(encoding="utf-8") + "\n# reviewed change\n",
        encoding="utf-8",
    )
    _, verification_changed = adapter.load_snapshot(fleet_root / "fleet.yaml")
    assert adapter.snapshot_hash(verification_changed) != initial_hash

    verification.write_text(
        next(item.content for item in initial.files if item.path == "project/verification.yaml"),
        encoding="utf-8",
    )
    prompt = fleet_root / "agents" / "engineer.md"
    prompt.write_text(prompt.read_text(encoding="utf-8") + "Changed.\n", encoding="utf-8")
    _, prompt_changed = adapter.load_snapshot(fleet_root / "fleet.yaml")
    assert adapter.snapshot_hash(prompt_changed) != initial_hash


def test_filesystem_config_limit_is_checked_before_content_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("oversized-project"))
    oversized = fleet_root / "agents" / "engineer.md"
    oversized.write_bytes(b"x" * (MAX_CONFIG_BYTES + 1))
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == oversized:
            raise AssertionError("oversized configuration was read before its size was rejected")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(FleetError) as captured:
        adapter.load_snapshot(fleet_root / "fleet.yaml")

    assert captured.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO support is unavailable")
def test_config_snapshot_rejects_special_file_without_opening_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("special-file-project"))
    special = fleet_root / "agents" / "engineer.md"
    special.unlink()
    os.mkfifo(special)
    original_read_bytes = Path.read_bytes

    def guarded_read_bytes(path: Path) -> bytes:
        if path == special:
            raise AssertionError("special configuration file was opened for blocking read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)

    with pytest.raises(FleetError) as captured:
        adapter.load_snapshot(fleet_root / "fleet.yaml")

    assert captured.value.code is ErrorCode.CONFIG_INVALID


def test_config_snapshot_rejects_parent_symlink_swap_without_outside_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("snapshot-parent-race"))
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = "outside-parent-symlink-sentinel"
    (outside / "engineer.md").write_text(sentinel, encoding="utf-8")
    moved = tmp_path / "moved-agents"
    original_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "agents" and dir_fd is not None and not swapped:
            swapped = True
            (fleet_root / "agents").rename(moved)
            (fleet_root / "agents").symlink_to(outside, target_is_directory=True)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)

    with pytest.raises(FleetError) as captured:
        adapter.load_snapshot(fleet_root / "fleet.yaml")

    assert captured.value.code in {ErrorCode.CONFIG_INVALID, ErrorCode.PATH_OUTSIDE_SCOPE}
    assert swapped is True
    assert sentinel not in str(captured.value)


def test_config_snapshot_rejects_file_growth_between_stat_and_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    fleet_root = tmp_path / ".fleet"
    adapter.apply(fleet_root, adapter.default_files("snapshot-growth-race"))
    target = fleet_root / "agents" / "engineer.md"
    original_open = os.open
    grown = False

    def growing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal grown
        if path == "engineer.md" and dir_fd is not None and not grown:
            grown = True
            target.write_bytes(b"x" * (MAX_CONFIG_BYTES + 1))
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", growing_open)

    with pytest.raises(FleetError) as captured:
        adapter.load_snapshot(fleet_root / "fleet.yaml")

    assert captured.value.code is ErrorCode.CONFIG_INVALID
    assert grown is True
