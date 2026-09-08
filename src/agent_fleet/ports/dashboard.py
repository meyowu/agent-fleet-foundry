from __future__ import annotations

from typing import Protocol

from agent_fleet.domain.dashboard import DashboardCatalog, DashboardCursors, DashboardReadFrame


class DashboardReader(Protocol):
    def catalog(self, project_id: str, *, before: int | None = None) -> DashboardCatalog: ...

    def frame(
        self, project_id: str, root_run_id: str, *, cursors: DashboardCursors | None = None
    ) -> DashboardReadFrame: ...
