from __future__ import annotations

import base64
from typing import Any

import pytest
from pydantic import ValidationError

from agent_fleet.domain.organization_tree import (
    OrganizationDirectory,
    OrganizationFile,
    OrganizationTree,
    OrganizationXattr,
)
from agent_fleet.domain.security import sha256_bytes


def file(path: str = "fleet.yaml", content: str = "name: test\n") -> OrganizationFile:
    return OrganizationFile(
        path=path, content=content, sha256=sha256_bytes(content.encode()), mode=0o644
    )


def tree() -> OrganizationTree:
    return OrganizationTree(
        files=(file("README.md"), file("agents/cos.yaml")),
        directories=(
            OrganizationDirectory(path=".", mode=0o755),
            OrganizationDirectory(path="agents", mode=0o700),
            OrganizationDirectory(path="empty", mode=0o755),
        ),
    )


def test_complete_tree_has_exact_stable_hash_and_strict_frozen_round_trip() -> None:
    original = tree()
    assert OrganizationTree.model_validate_json(original.model_dump_json()) == original
    assert len(original.sha256) == 64
    changed = original.model_dump(mode="json")
    changed["directories"][2]["mode"] = 0o700
    assert OrganizationTree.model_validate(changed, strict=False).sha256 != original.sha256
    with pytest.raises(ValidationError):
        original.files = ()  # type: ignore[misc]
    with pytest.raises(ValidationError):
        OrganizationTree.model_validate({**original.model_dump(), "extra": True})


@pytest.mark.parametrize(
    "path",
    [
        "",
        ".",
        "/fleet.yaml",
        "../fleet.yaml",
        "x/../fleet.yaml",
        "x//y",
        "x/./y",
        "x\\y",
        "x\ny",
        "x\x7fy",
        ".git/config",
        ".env",
        ".env.production",
        "a/secrets",
        "a/private.key",
        "a/id_rsa",
        "a/credentials.json",
        "\udcff",
        "/".join(["x"] * 17),
    ],
)
def test_unsafe_or_unbounded_paths_are_rejected(path: str) -> None:
    with pytest.raises(ValidationError):
        file(path)


@pytest.mark.parametrize("mode", [0o400, 0o666, 0o755, 0o4600, "384", True])
def test_file_modes_do_not_coerce_or_normalize(mode: Any) -> None:
    with pytest.raises(ValidationError):
        OrganizationFile.model_validate({**file().model_dump(), "mode": mode})


@pytest.mark.parametrize(
    "change", ["missing-root", "parent", "duplicate", "unordered", "casefold", "ancestor"]
)
def test_tree_requires_complete_nonconflicting_sorted_namespace(change: str) -> None:
    data = tree().model_dump()
    if change == "missing-root":
        data["directories"] = data["directories"][1:]
    elif change == "parent":
        data["files"] = (file("missing/x").model_dump(),)
    elif change == "duplicate":
        data["files"] = (data["files"][0], data["files"][0])
    elif change == "unordered":
        data["files"] = tuple(reversed(data["files"]))
    elif change == "casefold":
        data["files"] = (file("README.md").model_dump(), file("readme.md").model_dump())
    else:
        data["files"] = (file("agents").model_dump(),)
    with pytest.raises(ValidationError):
        OrganizationTree.model_validate(data)


def test_content_hash_and_file_and_aggregate_bounds_are_exact() -> None:
    with pytest.raises(ValidationError):
        OrganizationFile.model_validate({**file().model_dump(), "content": "different"})
    with pytest.raises(ValidationError):
        file(content="é" * 256_001)
    with pytest.raises(ValidationError):
        OrganizationFile(path="x", content="\udcff", sha256="a" * 64, mode=0o644)
    assert len(file(content="x" * 512_000).content) == 512_000
    root = (OrganizationDirectory(path=".", mode=0o700),)
    with pytest.raises(ValidationError):
        OrganizationTree(
            files=tuple(file(f"x{index:03}") for index in range(257)), directories=root
        )
    with pytest.raises(ValidationError):
        OrganizationTree(
            files=(),
            directories=root
            + tuple(OrganizationDirectory(path=f"x{index:03}", mode=0o700) for index in range(256)),
        )
    exact = tuple(file(f"x{index:02}", "x" * 500_000) for index in range(8))
    assert OrganizationTree(files=exact, directories=root)
    with pytest.raises(ValidationError):
        OrganizationTree(files=(*exact, file("z", "x")), directories=root)


@pytest.mark.parametrize(
    "value", ["?", "YQ", "YR==", "YQ==\n", "é", base64.b64encode(b"x" * 4097).decode()]
)
def test_metadata_rejects_noncanonical_or_oversized_base64(value: str) -> None:
    with pytest.raises(ValidationError):
        OrganizationXattr(name="com.apple.provenance", value_base64=value)


def test_metadata_name_cardinality_and_exact_bytes_affect_tree_identity() -> None:
    attribute = OrganizationXattr(
        name="com.apple.provenance", value_base64=base64.b64encode(b"\x00\xff").decode()
    )
    original = tree()
    changed = original.model_copy(
        update={
            "files": (
                original.files[0].model_copy(update={"xattrs": (attribute,)}),
                *original.files[1:],
            )
        }
    )
    assert changed.sha256 != original.sha256
    assert OrganizationTree.model_validate_json(changed.model_dump_json()) == changed
    with pytest.raises(ValidationError):
        OrganizationXattr.model_validate({"name": "com.apple.quarantine", "value_base64": ""})
    with pytest.raises(ValidationError):
        OrganizationFile.model_validate({**file().model_dump(), "xattrs": (attribute, attribute)})
