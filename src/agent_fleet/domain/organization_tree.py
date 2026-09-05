"""Bounded complete organization bytes and exact native-publication receipts."""

from __future__ import annotations

import base64
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from agent_fleet.domain.models import ProjectId, Sha256
from agent_fleet.domain.security import canonical_json_hash, sha256_bytes

OperationId = Annotated[str, StringConstraints(pattern=r"^fop_[0-9a-f]{32}$")]
MAX_FILES = 256
MAX_DIRECTORIES = 256
MAX_FILE_BYTES = 512_000
MAX_TREE_BYTES = 4_000_000
MAX_DEPTH = 16
_SENSITIVE = {
    ".git",
    ".hg",
    ".svn",
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".env",
    "credentials",
    "credentials.json",
    "credentials.yaml",
    "secrets",
    "secrets.json",
    "secrets.yaml",
    "id_rsa",
    "id_ed25519",
    "id_ecdsa",
    "trust",
    "state",
    "audit",
}


class _Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def validate_organization_path(value: str, *, root: bool = False) -> str:
    if value == "." and root:
        return value
    encoded = value.encode("utf-8")
    path = PurePosixPath(value)
    if (
        not encoded
        or len(encoded) > 4096
        or path.is_absolute()
        or path.as_posix() != value
        or "\\" in value
        or ".." in path.parts
        or not path.parts
        or len(path.parts) > MAX_DEPTH
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("organization paths must be bounded canonical relative paths")
    for part in path.parts:
        folded = part.casefold()
        if (
            folded in _SENSITIVE
            or folded.startswith(".env.")
            or folded.endswith((".pem", ".key", ".p12", ".pfx"))
        ):
            raise ValueError("organization paths cannot contain credential or VCS entries")
    return value


class OrganizationXattr(_Record):
    name: Literal["com.apple.provenance"]
    value_base64: str = Field(max_length=5464)

    @model_validator(mode="after")
    def bounded_canonical(self) -> OrganizationXattr:
        value = base64.b64decode(self.value_base64, validate=True)
        if len(value) > 4096 or base64.b64encode(value).decode("ascii") != self.value_base64:
            raise ValueError("organization metadata must be bounded canonical base64")
        return self


class OrganizationFile(_Record):
    path: str
    content: str
    sha256: Sha256
    mode: Literal[0o600, 0o644]
    xattrs: tuple[OrganizationXattr, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def checked(self) -> OrganizationFile:
        validate_organization_path(self.path)
        content = self.content.encode("utf-8")
        if len(content) > MAX_FILE_BYTES or sha256_bytes(content) != self.sha256:
            raise ValueError("organization file content exceeds its bound or hash")
        if type(self.mode) is not int:
            raise ValueError("organization file mode must be an integer")
        return self


class OrganizationDirectory(_Record):
    path: str
    mode: Literal[0o700, 0o755]
    xattrs: tuple[OrganizationXattr, ...] = Field(default=(), max_length=1)

    @model_validator(mode="after")
    def checked(self) -> OrganizationDirectory:
        validate_organization_path(self.path, root=True)
        if type(self.mode) is not int:
            raise ValueError("organization directory mode must be an integer")
        return self


class OrganizationTree(_Record):
    files: tuple[OrganizationFile, ...] = Field(max_length=MAX_FILES)
    directories: tuple[OrganizationDirectory, ...] = Field(min_length=1, max_length=MAX_DIRECTORIES)

    @property
    def sha256(self) -> str:
        return canonical_json_hash(self.model_dump(mode="json"))

    @model_validator(mode="after")
    def complete(self) -> OrganizationTree:
        file_paths = [item.path for item in self.files]
        directory_paths = [item.path for item in self.directories]
        if file_paths != sorted(set(file_paths)) or directory_paths != sorted(set(directory_paths)):
            raise ValueError("organization entries must be sorted and unique")
        if directory_paths.count(".") != 1:
            raise ValueError("organization tree needs exactly one root directory")
        all_paths = file_paths + directory_paths
        folded = {
            tuple(part.casefold() for part in PurePosixPath(path).parts) for path in all_paths
        }
        if len(folded) != len(all_paths):
            raise ValueError("organization entries have case-folded collisions")
        directories = set(directory_paths)
        for value in all_paths:
            if value != "." and str(PurePosixPath(value).parent) not in directories:
                raise ValueError("organization tree lacks complete directory parents")
        if sum(len(item.content.encode("utf-8")) for item in self.files) > MAX_TREE_BYTES:
            raise ValueError("organization tree exceeds its aggregate byte bound")
        return self


class DirectoryIdentity(_Record):
    device: int = Field(ge=0)
    inode: int = Field(gt=0)
    uid: int = Field(ge=0)
    mode: int = Field(ge=0, le=0o7777)


class PreparedPublication(_Record):
    operation_id: OperationId
    project_id: ProjectId
    repository_identity: Sha256
    repository_basename: str = Field(min_length=1, max_length=255)
    parent_identity: DirectoryIdentity
    repository_directory_identity: DirectoryIdentity
    target_identity: DirectoryIdentity
    scratch_basename: str = Field(pattern=r"^\.fleet-publication-fop_[0-9a-f]{32}$")
    scratch_identity: DirectoryIdentity
    staged_identity: DirectoryIdentity
    before_sha256: Sha256
    after_sha256: Sha256
    backend: Literal["darwin-renameatx_np", "linux-renameat2"]
    durability: Literal["fsync+fullfsync", "fsync"]

    @field_validator("repository_basename")
    @classmethod
    def component(cls, value: str) -> str:
        if (
            value in {".", ".."}
            or "/" in value
            or "\\" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError("repository basename must be one safe component")
        value.encode("utf-8")
        return value

    @model_validator(mode="after")
    def same_filesystem(self) -> PreparedPublication:
        identities = (
            self.parent_identity,
            self.repository_directory_identity,
            self.target_identity,
            self.scratch_identity,
            self.staged_identity,
        )
        if len({item.device for item in identities}) != 1:
            raise ValueError("publication identities must share one filesystem")
        if len({item.inode for item in identities}) != len(identities):
            raise ValueError("publication directories must have distinct identities")
        if self.scratch_identity.mode != 0o700 or self.scratch_basename != (
            ".fleet-publication-" + self.operation_id
        ):
            raise ValueError("publication scratch identity is invalid")
        if (self.backend == "darwin-renameatx_np") != (self.durability == "fsync+fullfsync"):
            raise ValueError("publication backend and durability disagree")
        return self


class PublicationObservation(_Record):
    prepared: PreparedPublication
    state: Literal["prepared", "exchanged", "cleaned"]
    target_identity: DirectoryIdentity
    target_sha256: Sha256
    backup_identity: DirectoryIdentity | None = None
    backup_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def coherent(self) -> PublicationObservation:
        before = (self.prepared.target_identity, self.prepared.before_sha256)
        after = (self.prepared.staged_identity, self.prepared.after_sha256)
        target = (self.target_identity, self.target_sha256)
        backup = (self.backup_identity, self.backup_sha256)
        if self.state == "prepared" and (target != before or backup != after):
            raise ValueError("prepared publication trees are inconsistent")
        if self.state == "exchanged" and (target != after or backup != before):
            raise ValueError("exchanged publication trees are inconsistent")
        if self.state == "cleaned" and (target not in {before, after} or backup != (None, None)):
            raise ValueError("cleaned publication trees are inconsistent")
        return self
