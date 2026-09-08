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
from agent_fleet.schemas.generate import SCHEMAS, generate


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


def test_adaptive_graph_public_schema_catalog_is_complete_and_bounded() -> None:
    expected = {
        "writer-assignment.schema.json",
        "specialist-report.schema.json",
        "graph-snapshot.schema.json",
        "graph-child-seed.schema.json",
        "graph-child-binding.schema.json",
        "graph-driver-claim.schema.json",
        "graph-artifact-ref.schema.json",
        "graph-node-record.schema.json",
        "graph-join-input.schema.json",
        "graph-join-preparation.schema.json",
        "graph-join-completion.schema.json",
        "graph-delivery-evidence.schema.json",
    }
    assert expected <= SCHEMAS.keys()
    for name in expected:
        assert SCHEMAS[name].model_json_schema()["additionalProperties"] is False
    graph = SCHEMAS["graph-snapshot.schema.json"].model_json_schema()
    assert graph["properties"]["nodes"]["maxItems"] == 16
    assert graph["properties"]["parent_run_id"]["pattern"] == r"^run_[0-9a-f]{32}$"
    assert set(graph["$defs"]["GraphStatus"]["enum"]) == {
        "ready",
        "running",
        "paused",
        "joined",
        "failed",
        "cancelled",
    }
    node = SCHEMAS["graph-node-record.schema.json"].model_json_schema()
    assert node["properties"]["revision"]["minimum"] == 0
    assert node["properties"]["input_artifacts"]["maxItems"] == 64
    seed = SCHEMAS["graph-child-seed.schema.json"].model_json_schema()
    assert seed["properties"]["iteration"]["const"] == 0
    assert {"parent_run_id", "parent_plan_sha256", "parent_node_id", "parent_iteration"} <= (
        seed["$defs"]["Run"]["properties"].keys()
    )
    specialist = SCHEMAS["specialist-report.schema.json"].model_json_schema()
    assert specialist["properties"]["role"]["pattern"] == r"^[a-z][a-z0-9_-]*$"
    assert specialist["properties"]["role"]["maxLength"] == 64
    assert specialist["properties"]["findings"]["maxItems"] == 32
    delivery = SCHEMAS["graph-delivery-evidence.schema.json"].model_json_schema()
    assert delivery["properties"]["child_cleanup_receipts"]["maxItems"] == 16
    assert delivery["properties"]["sequential_repair_iterations"]["maximum"] == 5


def test_conversation_public_schemas_keep_context_and_ownership_bounded() -> None:
    expected = {
        "conversation.schema.json",
        "conversation-summary.schema.json",
        "conversation-artifact-ref.schema.json",
        "conversation-context-entry.schema.json",
        "conversation-context.schema.json",
        "conversation-submission.schema.json",
        "conversation-run-binding.schema.json",
        "conversation-claim.schema.json",
        "conversation-turn.schema.json",
        "conversation-registration.schema.json",
    }
    assert expected <= SCHEMAS.keys()
    for name in expected:
        assert SCHEMAS[name].model_json_schema()["additionalProperties"] is False
    conversation = SCHEMAS["conversation.schema.json"].model_json_schema()["properties"]
    assert conversation["conversation_id"]["pattern"] == r"^conv_[0-9a-f]{32}$"
    assert conversation["project_id"]["pattern"] == r"^prj_[0-9a-f]{32}$"
    assert conversation["next_turn_sequence"]["maximum"] == 1001
    assert conversation["created_at"]["format"] == "date-time"
    context = SCHEMAS["conversation-context.schema.json"].model_json_schema()
    assert context["properties"]["entries"]["maxItems"] == 8
    assert context["properties"]["through_sequence"]["maximum"] == 1000
    entry = context["$defs"]["ConversationContextEntry"]["properties"]
    assert entry["turn_id"]["pattern"] == r"^turn_[0-9a-f]{32}$"
    assert entry["artifact_refs"]["maxItems"] == 8
    submission = SCHEMAS["conversation-submission.schema.json"].model_json_schema()["properties"]
    assert submission["submission_key"]["pattern"] == r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"
    assert not {"run_id", "provider_model", "credential_ref", "grant"}.intersection(submission)
    turn = SCHEMAS["conversation-turn.schema.json"].model_json_schema()
    assert turn["properties"]["artifact_refs"]["maxItems"] == 8
    assert set(turn["$defs"]["ConversationTurnStatus"]["enum"]) == {
        "running",
        "waiting",
        "delivered",
        "failed",
        "cancelled",
        "recovery_required",
    }
    binding = SCHEMAS["conversation-run-binding.schema.json"].model_json_schema()["properties"]
    assert {
        "budget_limits",
        "context_sha256",
        "run_binding_sha256",
        "submission_sha256",
    } <= binding.keys()
    claim = SCHEMAS["conversation-claim.schema.json"].model_json_schema()["properties"]
    assert claim["claim_id"]["pattern"] == r"^corr_[0-9a-f]{32}$"
    assert claim["generation"]["minimum"] == 1
    # UTF-8 byte totals, UTC-only offsets and cross-record identity are runtime
    # validators; JSON Schema's representable bounds do not replace those checks.


def test_organization_evolution_schemas_are_exact_bounded_and_non_authorizing() -> None:
    expected = {
        "workflow-definition.schema.json",
        "verification-skill.schema.json",
        "organization-xattr.schema.json",
        "organization-file.schema.json",
        "organization-directory.schema.json",
        "organization-tree.schema.json",
        "directory-identity.schema.json",
        "prepared-publication.schema.json",
        "publication-observation.schema.json",
        "organization-admission.schema.json",
        "organization-head.schema.json",
        "organization-version.schema.json",
        "fleet-patch-semantic-change.schema.json",
        "fleet-patch-proposal-record.schema.json",
        "organization-operation.schema.json",
        "organization-publication-result.schema.json",
        "organization-repository-boundary.schema.json",
    }
    assert expected <= SCHEMAS.keys()
    for name in expected:
        assert SCHEMAS[name].model_json_schema()["additionalProperties"] is False
    tree = SCHEMAS["organization-tree.schema.json"].model_json_schema()["properties"]
    assert tree["files"]["maxItems"] == 256 and tree["directories"]["maxItems"] == 256
    admission = SCHEMAS["organization-admission.schema.json"].model_json_schema()["properties"]
    assert admission["revision"]["minimum"] == 0
    operation = SCHEMAS["organization-operation.schema.json"].model_json_schema()["properties"]
    assert operation["authorization"]["enum"] == ["apply", "rollback"]
    assert "repository_before" in operation
    skill = SCHEMAS["verification-skill.schema.json"].model_json_schema()["properties"]
    assert set(skill) == {"apiVersion", "kind", "metadata", "appliesToPaths", "requiredCommandIds"}
    assert skill["requiredCommandIds"]["maxItems"] == 128
