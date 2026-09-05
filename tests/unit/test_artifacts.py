from __future__ import annotations

from pathlib import Path

import pytest

from agent_fleet.adapters.artifacts.local import LocalArtifactStore
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.security import sha256_bytes


def test_content_address_and_integrity(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    content = b"evidence\n"
    content_ref, digest, size = store.put(content)
    assert digest == sha256_bytes(content)
    assert size == len(content)
    assert store.get(content_ref, digest) == content

    (store.root / content_ref).write_bytes(b"tampered")
    with pytest.raises(FleetError) as captured:
        store.get(content_ref, digest)
    assert captured.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED


def test_bounded_read_rejects_oversize_even_with_matching_hash(tmp_path: Path) -> None:
    store = LocalArtifactStore(tmp_path / "artifacts")
    content_ref, digest, _ = store.put(b"123456789")
    assert store.get(content_ref, digest, max_bytes=9) == b"123456789"
    for bound in (8, 0, -1, True, 16_777_217):
        with pytest.raises(FleetError) as error:
            store.get(content_ref, digest, max_bytes=bound)
        assert error.value.code is ErrorCode.ARTIFACT_INTEGRITY_FAILED
