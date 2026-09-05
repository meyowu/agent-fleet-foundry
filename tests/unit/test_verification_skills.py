from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Any, Literal

import pytest
import yaml
from pydantic import ValidationError

from agent_fleet.adapters.config.yaml import (
    MAX_AGENT_GUIDANCE_BYTES,
    MAX_CONFIG_BYTES,
    MAX_CONFIG_SNAPSHOT_BYTES,
    YamlConfigurationAdapter,
)
from agent_fleet.domain.config import VerificationSkill, WorkflowDefinition
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import Redactor, sha256_bytes


def skill_data() -> dict[str, Any]:
    return {
        "apiVersion": "agentfleet.dev/v1alpha1",
        "kind": "VerificationSkill",
        "metadata": {"name": "backend-integration"},
        "appliesToPaths": ["backend"],
        "requiredCommandIds": ["integration"],
    }


def skill_files() -> dict[str, str]:
    files = YamlConfigurationAdapter().default_files("skill-project")
    workflow = yaml.safe_load(files["workflows/code-change.yaml"])
    workflow["verificationSkills"] = ["skills/backend-integration.yaml"]
    files["workflows/code-change.yaml"] = yaml.safe_dump(workflow, sort_keys=False)
    files["skills/backend-integration.yaml"] = yaml.safe_dump(skill_data(), sort_keys=False)
    profile = yaml.safe_load(files["project/verification.yaml"])
    profile["commands"] = {
        command_id: {
            "executable": "python",
            "argv": ["-m", "pytest", path],
            "cwd": ".",
            "timeoutSeconds": 60,
            "networkRequired": False,
        }
        for command_id, path in (("unit", "tests/unit"), ("integration", "tests/integration"))
    }
    profile["requiredForCodeChange"] = ["unit"]
    files["project/verification.yaml"] = yaml.safe_dump(profile, sort_keys=False)
    return files


def requirements(
    files: dict[str, str],
    paths: tuple[str, ...],
    *,
    change_kind: Literal["read_only", "code_change"] = "code_change",
) -> tuple[str, ...]:
    adapter = YamlConfigurationAdapter()
    spec, snapshot = adapter.snapshot_from_files(files)
    return adapter.required_verification_commands(
        spec, snapshot, workflow_id="code-change", allowed_paths=paths, change_kind=change_kind
    )


def test_no_skill_default_bytes_and_snapshot_hash_are_unchanged(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    files = adapter.default_files("legacy-no-skills")
    assert sha256_bytes(
        "".join(path + "\0" + value for path, value in sorted(files.items())).encode()
    ) == ("9d41941623f6931814e17fb9c35c44c176ba690c773f2103bcf1653e2074de09")
    spec, snapshot = adapter.snapshot_from_files(files)
    assert (
        adapter.snapshot_hash(snapshot)
        == "172d146caccd3344b05c023fdd27371cf6a9d94204d59c9c853004055eb59c49"
    )
    assert "verificationSkills" not in files["workflows/code-change.yaml"]
    assert "README.md" not in {item.path for item in snapshot.files}
    adapter.apply(tmp_path / ".fleet", files)
    assert adapter.load_snapshot(tmp_path / ".fleet/fleet.yaml") == (spec, snapshot)


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        (("backend",), ("integration", "unit")),
        (("backend/api.py",), ("integration", "unit")),
        (("BACKEND/api.py",), ("integration", "unit")),
        ((".",), ("integration", "unit")),
        (("frontend",), ("unit",)),
        (("backend-old",), ("unit",)),
        (("frontend", "backend/api.py"), ("integration", "unit")),
    ],
)
def test_conditional_requirements_use_component_overlap(
    paths: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    assert requirements(skill_files(), paths) == expected


def test_parent_scope_matches_narrow_skill_and_read_only_requires_no_commands() -> None:
    files = skill_files()
    skill = skill_data()
    skill["appliesToPaths"] = ["backend/api"]
    files["skills/backend-integration.yaml"] = yaml.safe_dump(skill)
    assert requirements(files, ("backend",)) == ("integration", "unit")
    assert requirements(files, (), change_kind="read_only") == ()


def test_skill_closure_preserves_bytes_and_reopens(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    files = skill_files()
    files["skills/backend-integration.yaml"] += "\n# reviewed Unicode: 中文\r\n"
    files["unreferenced.md"] = "not part of the reference snapshot\n"
    spec, expected = adapter.snapshot_from_files(files)
    adapter.apply(tmp_path / ".fleet", files)
    reopened_spec, reopened = YamlConfigurationAdapter().load_snapshot(
        tmp_path / ".fleet/fleet.yaml"
    )
    assert (reopened_spec, reopened) == (spec, expected)
    assert [item.path for item in reopened.files] == sorted(item.path for item in reopened.files)
    skill = next(item for item in reopened.files if item.path == "skills/backend-integration.yaml")
    assert skill.content == files[skill.path]
    assert skill.sha256 == sha256_bytes(files[skill.path].encode())
    assert "unreferenced.md" not in {item.path for item in reopened.files}
    assert adapter.required_verification_commands(
        reopened_spec,
        reopened,
        workflow_id="code-change",
        allowed_paths=("backend",),
        change_kind="code_change",
    ) == ("integration", "unit")


def test_duplicate_requirements_from_multiple_skills_are_sorted_once() -> None:
    files = skill_files()
    second = skill_data()
    second["metadata"] = {"name": "backend-quality"}
    second["requiredCommandIds"] = ["unit", "integration"]
    files["skills/backend-quality.yaml"] = yaml.safe_dump(second)
    workflow = yaml.safe_load(files["workflows/code-change.yaml"])
    workflow["verificationSkills"].append("skills/backend-quality.yaml")
    files["workflows/code-change.yaml"] = yaml.safe_dump(workflow)
    assert requirements(files, ("backend",)) == ("integration", "unit")


@pytest.mark.parametrize(
    "reference",
    [
        "../outside.yaml",
        "/tmp/skill.yaml",
        "skills/../skill.yaml",
        "skills/nested/x.yaml",
        "Skills/backend-integration.yaml",
        "skills/backend-integration.yml",
        "skills/back\\end.yaml",
        "skills/line\nbreak.yaml",
        "skills/backend-integration.yaml/",
        "skills/雪.yaml",
        "skills/" + "x" * 120 + ".yaml",
        "skills/.hidden.yaml",
        "skills/-hidden.yaml",
    ],
)
def test_skill_reference_is_strict(reference: str) -> None:
    files = skill_files()
    workflow = yaml.safe_load(files["workflows/code-change.yaml"])
    workflow["verificationSkills"] = [reference]
    files["workflows/code-change.yaml"] = yaml.safe_dump(workflow)
    with pytest.raises(FleetError) as caught:
        YamlConfigurationAdapter().snapshot_from_files(files)
    assert caught.value.code is ErrorCode.CONFIG_INVALID


@pytest.mark.parametrize(
    "paths",
    [
        ["../x"],
        ["/x"],
        [".fleet"],
        ["src/.GIT/config"],
        ["backend/*"],
        ["x\\y"],
        ["x:y"],
        ["backend", "BACKEND"],
        ["bad\npath"],
        ["bad\ud800path"],
        ["a/" * 65 + "file"],
        [],
    ],
)
def test_skill_scope_rejects_noncanonical_protected_or_duplicate_paths(paths: list[str]) -> None:
    data = skill_data()
    data["appliesToPaths"] = paths
    with pytest.raises(ValidationError):
        VerificationSkill.model_validate(data)


@pytest.mark.parametrize(
    "field",
    [
        "executable",
        "script",
        "allowedTools",
        "permissions",
        "credentialRef",
        "sandbox",
        "mayDelegateTo",
    ],
)
def test_skill_has_no_executable_or_authority_fields(field: str) -> None:
    files = skill_files()
    data = skill_data()
    data[field] = "untrusted"
    files["skills/backend-integration.yaml"] = yaml.safe_dump(data)
    with pytest.raises(FleetError, match="extra_forbidden"):
        YamlConfigurationAdapter().validate_files(files)


@pytest.mark.parametrize(
    "command_ids",
    [[], ["integration", "integration"], ["unknown"], ["Invalid"], ["integration"] * 129],
)
def test_invalid_skill_command_references_fail(command_ids: list[str]) -> None:
    files = skill_files()
    data = skill_data()
    data["requiredCommandIds"] = command_ids
    files["skills/backend-integration.yaml"] = yaml.safe_dump(data)
    with pytest.raises(FleetError):
        YamlConfigurationAdapter().validate_files(files)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "skill-name",
        "workflow-name",
        "workflow-reference",
        "stages",
        "limits",
        "duplicate",
        "case-alias",
        "too-many",
        "hooks",
    ],
)
def test_incoherent_workflow_closure_fails(change: str) -> None:
    files = skill_files()
    workflow = yaml.safe_load(files["workflows/code-change.yaml"])
    if change == "missing":
        del files["skills/backend-integration.yaml"]
    elif change == "skill-name":
        data = skill_data()
        data["metadata"] = {"name": "other"}
        files["skills/backend-integration.yaml"] = yaml.safe_dump(data)
    elif change == "workflow-name":
        workflow["metadata"]["name"] = "other"
    elif change == "workflow-reference":
        spec = yaml.safe_load(files["fleet.yaml"])
        spec["spec"]["workflows"]["code-change"]["definition"] = "workflows/other.yaml"
        files["fleet.yaml"] = yaml.safe_dump(spec)
        files["workflows/other.yaml"] = files["workflows/code-change.yaml"]
    elif change == "stages":
        workflow["stages"][4] = "applying"
    elif change == "limits":
        workflow["limits"]["maxRepairIterations"] = 2
    elif change == "duplicate":
        workflow["verificationSkills"] *= 2
    elif change == "case-alias":
        workflow["verificationSkills"].append("skills/BACKEND-INTEGRATION.yaml")
    elif change == "too-many":
        workflow["verificationSkills"] = [f"skills/skill-{index}.yaml" for index in range(33)]
    else:
        workflow["hooks"] = {"beforeVerification": "sh -c anything"}
    files["workflows/code-change.yaml"] = yaml.safe_dump(workflow)
    with pytest.raises(FleetError):
        YamlConfigurationAdapter().snapshot_from_files(files)


@pytest.mark.parametrize(
    "reference",
    [
        "fleet.yaml",
        "workflows/code-change.yaml",
        "project/verification.yaml",
        "skills/backend-integration.yaml",
    ],
)
def test_duplicate_yaml_keys_are_rejected_everywhere(reference: str) -> None:
    files = skill_files()
    files[reference] += "kind: replaced\n"
    with pytest.raises(FleetError, match="unique string keys") as caught:
        YamlConfigurationAdapter().validate_files(files)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "content",
    [
        "x: &x []\ny: *x\n",
        "!!python/object/apply:os.system ['id']\n",
        "[]\n",
        "bad: [\n",
        "x: " + "[" * 65 + "0" + "]" * 65,
        "appliesToPaths: [backend]\nappliesToPaths: [frontend]\n",
    ],
)
def test_skill_yaml_abuse_is_rejected(content: str) -> None:
    files = skill_files()
    files["skills/backend-integration.yaml"] = content
    with pytest.raises(FleetError):
        YamlConfigurationAdapter().snapshot_from_files(files)


@pytest.mark.parametrize(
    "change", ["shell", "network", "argv", "cwd", "duplicate-required", "invalid-id"]
)
def test_skill_commands_must_use_supported_canonical_profiles(change: str) -> None:
    files = skill_files()
    profile = yaml.safe_load(files["project/verification.yaml"])
    command = profile["commands"]["integration"]
    if change == "shell":
        command["executable"] = "bash"
    elif change == "network":
        command["networkRequired"] = True
    elif change == "argv":
        command["argv"] = ["x" * 4097]
    elif change == "cwd":
        command["cwd"] = "../escape"
    elif change == "duplicate-required":
        profile["requiredForCodeChange"] = ["unit", "unit"]
    else:
        profile["commands"]["BAD"] = profile["commands"].pop("integration")
    files["project/verification.yaml"] = yaml.safe_dump(profile)
    with pytest.raises(FleetError):
        YamlConfigurationAdapter().validate_files(files)


@pytest.mark.parametrize("kind", ["spec", "hash", "extra", "duplicate"])
def test_requirement_resolver_rejects_inconsistent_snapshot(kind: str) -> None:
    adapter = YamlConfigurationAdapter()
    spec, snapshot = adapter.snapshot_from_files(skill_files())
    if kind == "spec":
        spec = spec.model_copy(
            update={"metadata": spec.metadata.model_copy(update={"name": "other"})}
        )
    elif kind == "hash":
        snapshot = snapshot.model_copy(
            update={
                "files": [
                    snapshot.files[0].model_copy(update={"sha256": "0" * 64}),
                    *snapshot.files[1:],
                ]
            }
        )
    elif kind == "extra":
        snapshot = snapshot.model_copy(
            update={
                "files": [
                    *snapshot.files,
                    snapshot.files[0].model_copy(update={"path": "extra.md"}),
                ]
            }
        )
    else:
        snapshot = snapshot.model_copy(update={"files": [*snapshot.files, snapshot.files[0]]})
    with pytest.raises(FleetError):
        adapter.required_verification_commands(
            spec,
            snapshot,
            workflow_id="code-change",
            allowed_paths=("backend",),
            change_kind="code_change",
        )


@pytest.mark.parametrize(
    "paths", [(), ("backend", "BACKEND"), ("../x",), (".fleet",), ("bad\ud800path",)]
)
def test_requirement_resolver_rejects_invalid_code_scope(paths: tuple[str, ...]) -> None:
    with pytest.raises(FleetError):
        requirements(skill_files(), paths)


def test_unknown_workflow_is_rejected_even_for_read_only() -> None:
    adapter = YamlConfigurationAdapter()
    spec, snapshot = adapter.snapshot_from_files(skill_files())
    with pytest.raises(FleetError):
        adapter.required_verification_commands(
            spec, snapshot, workflow_id="unknown", allowed_paths=(), change_kind="read_only"
        )


@pytest.mark.parametrize(
    "path",
    [
        "SKILLS/extra.yaml",
        "skills",
        "skills/backend-integration.yaml/child",
        "line\nbreak",
        "bad\ud800path",
        "skills/.git/config",
    ],
)
def test_prospective_file_tree_rejects_aliases_ancestry_and_unsafe_paths(path: str) -> None:
    files = skill_files()
    files[path] = "untrusted"
    with pytest.raises(FleetError):
        YamlConfigurationAdapter().snapshot_from_files(files)


@pytest.mark.parametrize("kind", ["file", "utf8-file", "aggregate", "guidance", "invalid-utf8"])
def test_bounds_fail_before_prospective_publication(tmp_path: Path, kind: str) -> None:
    files = skill_files()
    if kind == "file":
        files["skills/backend-integration.yaml"] = "x" * (MAX_CONFIG_BYTES + 1)
    elif kind == "utf8-file":
        files["skills/backend-integration.yaml"] = "雪" * (MAX_CONFIG_BYTES // 3 + 1)
    elif kind == "aggregate":
        for index in range(MAX_CONFIG_SNAPSHOT_BYTES // MAX_CONFIG_BYTES + 1):
            files[f"extra/{index}.md"] = "x" * MAX_CONFIG_BYTES
    elif kind == "guidance":
        files["agents/cos.md"] = "x" * (MAX_AGENT_GUIDANCE_BYTES + 1)
    else:
        files["skills/backend-integration.yaml"] = "invalid\ud800content"
    with pytest.raises(FleetError) as caught:
        YamlConfigurationAdapter().apply(tmp_path / ".fleet", files)
    assert not (tmp_path / ".fleet").exists()
    assert caught.value.__context__ is None


@pytest.mark.parametrize("placement", ["raw", "encoded", "malformed", "path"])
def test_registered_secret_never_reaches_error_chain_or_disk(
    tmp_path: Path, placement: str
) -> None:
    secret = "REGISTERED-SKILL-SECRET"
    files = skill_files()
    if placement == "raw":
        files["skills/backend-integration.yaml"] += "unknown: " + secret + "\n"
    elif placement == "encoded":
        files["skills/backend-integration.yaml"] += (
            'unknown: "' + "".join(f"\\u{ord(char):04x}" for char in secret) + '"\n'
        )
    elif placement == "malformed":
        files["skills/backend-integration.yaml"] = "[" + secret
    else:
        files[secret] = "data"
    with pytest.raises(FleetError) as caught:
        YamlConfigurationAdapter(Redactor([secret])).apply(tmp_path / ".fleet", files)
    assert not (tmp_path / ".fleet").exists()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert secret not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "replacement", ["symlink", "parent-symlink", "hardlink", "fifo", "invalid-utf8", "oversized"]
)
def test_filesystem_skill_references_fail_closed(tmp_path: Path, replacement: str) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    files = skill_files()
    adapter.apply(root, files)
    target = root / "skills/backend-integration.yaml"
    before = (root / "fleet.yaml").read_bytes()
    secret = "INVALID-UTF8-SKILL-SECRET"
    if replacement == "parent-symlink":
        (root / "skills").rename(tmp_path / "moved-skills")
        (root / "skills").symlink_to(tmp_path / "moved-skills", target_is_directory=True)
    elif replacement in {"symlink", "hardlink"}:
        outside = tmp_path / "outside.yaml"
        outside.write_text(files["skills/backend-integration.yaml"])
        target.unlink()
        if replacement == "symlink":
            target.symlink_to(outside)
        else:
            os.link(outside, target)
    elif replacement == "fifo":
        target.unlink()
        os.mkfifo(target)
    elif replacement == "invalid-utf8":
        target.write_bytes(b"\xff" + secret.encode())
    else:
        target.write_bytes(b"x" * (MAX_CONFIG_BYTES + 1))
    with pytest.raises(FleetError) as caught:
        YamlConfigurationAdapter(Redactor([secret])).load_snapshot(root / "fleet.yaml")
    assert caught.value.code in {ErrorCode.CONFIG_INVALID, ErrorCode.PATH_OUTSIDE_SCOPE}
    assert secret not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert (root / "fleet.yaml").read_bytes() == before


def test_workflow_model_preserves_optional_empty_skill_default() -> None:
    files = YamlConfigurationAdapter().default_files("old-config")
    definition = WorkflowDefinition.model_validate(
        yaml.safe_load(files["workflows/code-change.yaml"])
    )
    assert definition.verification_skills == []


@pytest.mark.parametrize("count", [32, 33])
def test_command_surface_fits_the_runtime_task_ceiling(count: int) -> None:
    files = skill_files()
    profile = yaml.safe_load(files["project/verification.yaml"])
    command = profile["commands"]["unit"]
    for index in range(count - len(profile["commands"])):
        profile["commands"][f"additional-{index}"] = {**command, "argv": list(command["argv"])}
    files["project/verification.yaml"] = yaml.safe_dump(profile)
    if count == 32:
        assert requirements(files, ("backend",)) == ("integration", "unit")
    else:
        with pytest.raises(FleetError, match="too_long"):
            YamlConfigurationAdapter().snapshot_from_files(files)


def test_unchanged_unreferenced_skill_does_not_enter_reference_snapshot() -> None:
    adapter = YamlConfigurationAdapter()
    files = skill_files()
    original = adapter.snapshot_from_files(files)
    files["skills/unreferenced.yaml"] = "not a referenced skill definition\n"
    assert adapter.snapshot_from_files(files) == original


def test_skill_content_change_changes_config_identity() -> None:
    adapter = YamlConfigurationAdapter()
    files = skill_files()
    _, original = adapter.snapshot_from_files(files)
    files["skills/backend-integration.yaml"] += "# reviewed comment\n"
    _, changed = adapter.snapshot_from_files(files)
    assert adapter.snapshot_hash(changed) != adapter.snapshot_hash(original)


def test_invalid_utf8_diagnostic_drops_raw_unregistered_decoder_context(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    adapter.apply(root, skill_files())
    sentinel = "UNREGISTERED-RAW-DECODER-SENTINEL"
    (root / "skills/backend-integration.yaml").write_bytes(b"\xff" + sentinel.encode())
    with pytest.raises(FleetError) as caught:
        adapter.load_snapshot(root / "fleet.yaml")
    assert sentinel not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_filesystem_skill_growth_is_rejected_before_opened_content_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    adapter.apply(root, skill_files())
    target = root / "skills/backend-integration.yaml"
    original_open = os.open
    grown = False

    def grow_before_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal grown
        if path == "backend-integration.yaml" and dir_fd is not None and not grown:
            grown = True
            target.write_bytes(b"x" * (MAX_CONFIG_BYTES + 1))
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", grow_before_open)
    with pytest.raises(FleetError):
        adapter.load_snapshot(root / "fleet.yaml")
    assert grown is True


def test_existing_invalid_utf8_init_target_does_not_leak_decoder_context(tmp_path: Path) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    files = skill_files()
    adapter.apply(root, files)
    target = root / "skills/backend-integration.yaml"
    sentinel = "EXISTING-TARGET-DECODER-SENTINEL"
    before = b"\xff" + sentinel.encode()
    target.write_bytes(before)
    with pytest.raises(FleetError) as caught:
        adapter.apply(root, files)
    assert sentinel not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert target.read_bytes() == before


def test_invalid_utf8_target_race_rolls_back_without_retaining_raw_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = YamlConfigurationAdapter()
    root = tmp_path / ".fleet"
    sentinel = "RACING-TARGET-DECODER-SENTINEL"
    original_check = adapter.check_apply

    def change_after_check(path: Path, files: dict[str, str]) -> Any:
        spec = original_check(path, files)
        root.mkdir()
        (root / "skills").mkdir()
        (root / "skills/backend-integration.yaml").write_bytes(b"\xff" + sentinel.encode())
        return spec

    monkeypatch.setattr(adapter, "check_apply", change_after_check)
    with pytest.raises(FleetError) as caught:
        adapter.apply(root, skill_files())
    assert sentinel not in "".join(traceback.format_exception(caught.value))
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert not (root / "fleet.yaml").exists()
    assert (root / "skills/backend-integration.yaml").read_bytes() == b"\xff" + sentinel.encode()
