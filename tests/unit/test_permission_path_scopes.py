from __future__ import annotations

import pytest
from test_permission_broker import _fake_capabilities, _intent, _task

from agent_fleet.application.permissions import BaselinePermissionBroker
from agent_fleet.domain.models import CanonicalResource, PermissionOutcome


@pytest.mark.parametrize("path", ["src/new.py", "src/nested/new.py", "SRC/new.py"])
def test_directory_write_scope_includes_new_descendants(path: str) -> None:
    task = _task().model_copy(update={"allowed_paths": ["src"]})
    intent = _intent(
        action="workspace.write_file",
        resource=CanonicalResource(kind="workspace_path", identifier=path),
        parameters={"content": "new text"},
        side_effect=True,
    )
    decision = BaselinePermissionBroker().evaluate(intent, task, _fake_capabilities())
    assert decision.outcome is PermissionOutcome.ALLOW


@pytest.mark.parametrize("path", ["src", ".", "src2/new.py", "src/../new.py", "src//new.py"])
@pytest.mark.parametrize("action", ["workspace.write_file", "repo.read_file"])
def test_narrow_scope_never_becomes_parent_or_similarly_named_path(
    path: str,
    action: str,
) -> None:
    task = _task().model_copy(update={"allowed_paths": ["src/new.py"]})
    intent = _intent(
        action=action,
        resource=CanonicalResource(kind="workspace_path", identifier=path),
        parameters={"content": "new text"} if action.startswith("workspace") else {},
        side_effect=action.startswith("workspace"),
    )
    decision = BaselinePermissionBroker().evaluate(intent, task, _fake_capabilities())
    assert decision.outcome is PermissionOutcome.DENY


def test_forbidden_intersection_remains_denied_under_directory_scope() -> None:
    task = _task().model_copy(update={"allowed_paths": ["src"], "forbidden_paths": ["src/private"]})
    intent = _intent(
        action="workspace.write_file",
        resource=CanonicalResource(kind="workspace_path", identifier="src/private/key"),
        parameters={"content": "new text"},
        side_effect=True,
    )
    assert (
        BaselinePermissionBroker().evaluate(intent, task, _fake_capabilities()).outcome
        is PermissionOutcome.DENY
    )
