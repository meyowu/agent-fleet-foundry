from __future__ import annotations

from pathlib import Path
from typing import Protocol


class WorkspaceFileSystem(Protocol):
    def list_files(self, root: Path, *, max_entries: int = 4096) -> list[str]: ...

    def read_text(self, root: Path, logical_path: str, *, max_bytes: int = 200_000) -> str: ...

    def search_text(
        self,
        root: Path,
        query: str,
        *,
        logical_paths: list[str] | None = None,
        max_results: int = 200,
        max_total_bytes: int = 2_000_000,
    ) -> list[dict[str, object]]: ...

    def write_text(self, root: Path, logical_path: str, content: str) -> int: ...

    def apply_edit(
        self,
        root: Path,
        logical_path: str,
        *,
        expected_sha256: str,
        old: str,
        new: str,
        expected_matches: int,
    ) -> int: ...

    def delete_file(self, root: Path, logical_path: str, *, expected_sha256: str) -> None: ...
