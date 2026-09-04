from __future__ import annotations

from pathlib import Path

from agent_fleet.domain.config import FleetSpec
from agent_fleet.domain.evidence import CommandEvidence, EvidenceBundle
from agent_fleet.domain.fleet_patch import FleetPatch
from agent_fleet.domain.fleet_plan import FleetPlan
from agent_fleet.domain.models import (
    ImplementationReport,
    SandboxCapabilities,
    ScopeDecision,
    TaskSpec,
    ToolIntent,
    UsageRecord,
)
from agent_fleet.schemas.generate import generate


def test_schema_regeneration_has_no_diff() -> None:
    schema_root = Path(__file__).parents[2] / "src" / "agent_fleet" / "schemas"
    assert generate(schema_root, check=True) == 0


def test_generated_wire_schemas_expose_representable_security_constraints() -> None:
    fleet = FleetSpec.model_json_schema()
    runtime = fleet["$defs"]["RuntimeRequest"]
    capabilities = runtime["properties"]["requiredCapabilities"]
    assert capabilities["uniqueItems"] is True
    assert capabilities["allOf"] == [
        {"contains": {"const": "structured_output"}},
        {"contains": {"const": "tool_calling"}},
    ]
    assert runtime["allOf"][0]["then"]["properties"]["providerModel"] == {"type": "null"}
    assert runtime["allOf"][1]["then"]["required"] == ["providerModel"]

    task = TaskSpec.model_json_schema()
    assert task["properties"]["task_id"]["pattern"] == r"^task_[0-9a-f]{32}$"
    assert task["properties"]["run_id"]["pattern"] == r"^run_[0-9a-f]{32}$"

    intent = ToolIntent.model_json_schema()
    assert intent["properties"]["intent_id"]["pattern"] == r"^intent_[0-9a-f]{32}$"
    assert intent["properties"]["agent_instance_id"]["pattern"] == (r"^agent_[0-9a-f]{32}$")

    scope = ScopeDecision.model_json_schema()
    assert scope["additionalProperties"] is False
    assert scope["properties"]["allowed_paths"]["maxItems"] == 128

    implementation = ImplementationReport.model_json_schema()
    assert implementation["additionalProperties"] is False
    assert implementation["properties"]["intended_changed_paths"]["maxItems"] == 128

    usage = UsageRecord.model_json_schema()
    assert usage["additionalProperties"] is False
    assert usage["properties"]["requests"]["anyOf"][0]["maximum"] == 1_000_000

    plan = FleetPlan.model_json_schema()
    assert plan["properties"]["plan_id"]["pattern"] == r"^plan_[0-9a-f]{32}$"
    assert plan["properties"]["run_id"]["pattern"] == r"^run_[0-9a-f]{32}$"
    assert plan["properties"]["task_id"]["pattern"] == r"^task_[0-9a-f]{32}$"
    plan_scope = plan["$defs"]["FleetPlanNode"]["properties"]["scope"]
    assert plan_scope["maxItems"] == 128
    assert "pattern" in plan_scope["items"]

    patch = FleetPatch.model_json_schema()
    assert patch["properties"]["fleet_patch_id"]["pattern"] == r"^fpatch_[0-9a-f]{32}$"
    assert patch["properties"]["project_id"]["pattern"] == r"^prj_[0-9a-f]{32}$"
    patch_path = patch["$defs"]["FleetPatchFileChange"]["properties"]["path"]
    assert patch_path["pattern"].startswith(r"^\.fleet/")
    assert patch_path["maxLength"] == 4096

    sandbox = SandboxCapabilities.model_json_schema()
    assert sandbox["properties"]["provider"]["pattern"] == r"^[a-z][a-z0-9_-]*$"
    modes = sandbox["properties"]["supported_network_modes"]
    assert modes["minItems"] == 1
    assert modes["maxItems"] == 2
    assert set(modes["items"]["enum"]) == {"none", "approved-unrestricted"}

    command = CommandEvidence.model_json_schema()
    assert command["properties"]["evidence_id"]["pattern"] == r"^art_[0-9a-f]{32}$"
    assert command["properties"]["run_id"]["pattern"] == r"^run_[0-9a-f]{32}$"

    bundle = EvidenceBundle.model_json_schema()
    assert bundle["properties"]["project_id"]["pattern"] == r"^prj_[0-9a-f]{32}$"
    assert bundle["properties"]["config_snapshot_artifact_id"]["pattern"] == (r"^art_[0-9a-f]{32}$")
