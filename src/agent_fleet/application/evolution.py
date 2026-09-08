"""Reviewed organization proposals, exact generation admission and publication."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from agent_fleet.application.artifacts import ArtifactService
from agent_fleet.application.evolution_context import (
    EvolutionContext,
    build_evolution_context,
    validate_context_proposal,
)
from agent_fleet.application.model_profiles import ModelProfileService
from agent_fleet.domain.config import ConfigSnapshot
from agent_fleet.domain.errors import ErrorCode, FleetError
from agent_fleet.domain.evolution import (
    FleetPatchProposalRecord,
    OrganizationAdmission,
    OrganizationHead,
    OrganizationOperation,
    OrganizationPublicationResult,
    OrganizationVersion,
    describe_fleet_patch,
    evolve_tree,
)
from agent_fleet.domain.ids import IdPrefix
from agent_fleet.domain.models import (
    ArtifactKind,
    FleetPatch,
    FleetPatchFileChange,
    FleetPatchOperation,
    Project,
    Run,
)
from agent_fleet.domain.organization_tree import (
    OrganizationTree,
    PreparedPublication,
    PublicationObservation,
)
from agent_fleet.domain.security import Redactor, canonical_json_hash
from agent_fleet.domain.session_review import OrganizationReview
from agent_fleet.ports.clock import Clock
from agent_fleet.ports.config import ConfigurationPort
from agent_fleet.ports.evolution import OrganizationStore
from agent_fleet.ports.id_generator import IdGenerator
from agent_fleet.ports.organization_filesystem import (
    OrganizationFileSystem,
    OrganizationPublicationSession,
)
from agent_fleet.ports.repository import RepositoryPort
from agent_fleet.ports.secret_store import SecretNotConfiguredError, SecretStore, SecretStoreError
from agent_fleet.ports.state_store import StateStore

MAX_PROPOSAL_ARTIFACT_BYTES = 8_000_000


class OrganizationService:
    def __init__(
        self,
        state: StateStore,
        store: OrganizationStore,
        files: OrganizationFileSystem,
        config: ConfigurationPort,
        repository: RepositoryPort,
        artifacts: ArtifactService,
        clock: Clock,
        ids: IdGenerator,
        redactor: Redactor,
        secrets: SecretStore,
        *,
        model_profiles: ModelProfileService | None = None,
    ) -> None:
        self.state = state
        self.store = store
        self.files = files
        self.config = config
        self.repository = repository
        self.artifacts = artifacts
        self.clock = clock
        self.ids = ids
        self.redactor = redactor
        self.secrets = secrets
        self.model_profiles = model_profiles

    def project_for_path(self, path: Path) -> Project:
        repository = self.repository.inspect(path)
        project = self.state.get_project_by_root(repository.root)
        if project is None or project.identity_hash != repository.identity_hash:
            raise _conflict("The selected repository has no matching registered organization.")
        self.register_project_secrets(project)
        return self.state.get_project(project.project_id)

    def get_proposal(self, proposal_id: str) -> FleetPatchProposalRecord:
        proposal = self.store.get_proposal(proposal_id)
        run = self.state.get_run(proposal.source_run_id)
        self.register_run_secrets(run)
        # Re-read all payloads with the now-current explicit credential registry.
        return self.store.get_proposal(proposal_id)

    def list_proposals(
        self, path: Path, *, limit: int = 50
    ) -> tuple[FleetPatchProposalRecord, ...]:
        project = self.project_for_path(path)
        proposals = self.store.list_proposals(project.project_id, limit=limit)
        return tuple(self.get_proposal(item.patch.fleet_patch_id) for item in proposals)

    def get_operation(self, operation_id: str) -> OrganizationOperation:
        operation = self.store.get_operation(operation_id)
        self.get_proposal(operation.proposal_id)
        return self.store.get_operation(operation_id)

    def review(
        self, proposal_id: str, *, action: Literal["apply", "rollback"]
    ) -> tuple[OrganizationReview, FleetPatchProposalRecord]:
        proposal = self.get_proposal(proposal_id)
        project = self.state.get_project(proposal.base.project_id)
        with self.files.session(project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)) as session:
            expected = self._review_binding(proposal, project, session, action=action)
            operation = self.store.operation_for_proposal(proposal_id)
            if action == "apply" and (
                proposal.patch.rollback_of is not None
                or operation is not None
                or proposal.base != expected.organization.admission
            ):
                raise _conflict("Review requires an unapplied proposal for the current generation.")
            if action == "rollback" and (
                operation is None
                or operation.status != "committed"
                or operation.committed_version != expected.organization.revision
            ):
                raise _conflict("Rollback review requires the exact currently applied proposal.")
            return expected, proposal

    def _review_binding(
        self,
        proposal: FleetPatchProposalRecord,
        project: Project,
        session: OrganizationPublicationSession,
        *,
        action: Literal["apply", "rollback"],
    ) -> OrganizationReview:
        head, _ = self._capture_head(project, session)
        return OrganizationReview(
            proposal_id=proposal.patch.fleet_patch_id,
            action=action,
            proposal_sha256=proposal.proposal_sha256,
            project_sha256=canonical_json_hash(project.model_dump(mode="json")),
            repository_sha256=canonical_json_hash(
                self.repository.inspect_organization_boundary(
                    Path(project.canonical_root)
                ).model_dump(mode="json")
            ),
            organization=head,
        )

    def _check_review(
        self,
        expected: OrganizationReview | None,
        proposal: FleetPatchProposalRecord,
        project: Project,
        session: OrganizationPublicationSession,
        *,
        action: Literal["apply", "rollback"],
    ) -> None:
        if expected is not None and expected != self._review_binding(
            proposal, project, session, action=action
        ):
            raise _conflict("The exact reviewed proposal, action or organization head changed.")

    def apply(
        self,
        proposal_id: str,
        *,
        expected_review: OrganizationReview | None = None,
        validate_review: Callable[[], None] | None = None,
    ) -> OrganizationPublicationResult:
        """User-authorized application; this method is never a model tool."""
        proposal = self.get_proposal(proposal_id)
        operation = self.store.operation_for_proposal(proposal_id)
        if operation is not None and expected_review is None:
            return self._repeat(operation)
        if proposal.patch.rollback_of is not None:
            raise _conflict("An inverse proposal is applied only by explicit rollback.")
        project = self.state.get_project(proposal.base.project_id)
        operation_id = self.ids.new(IdPrefix.ORGANIZATION_OPERATION)
        with self.files.session(project, operation_id) as session:
            proposal = self.get_proposal(proposal_id)
            if validate_review is not None:
                validate_review()
            self._check_review(expected_review, proposal, project, session, action="apply")
            return self._publish(
                project, proposal, session, operation_id=operation_id, authorization="apply"
            )

    def rollback(
        self,
        proposal_id: str,
        *,
        expected_review: OrganizationReview | None = None,
        validate_review: Callable[[], None] | None = None,
    ) -> OrganizationPublicationResult:
        original = self.get_proposal(proposal_id)
        project = self.state.get_project(original.base.project_id)
        operation_id = self.ids.new(IdPrefix.ORGANIZATION_OPERATION)
        with self.files.session(project, operation_id) as session:
            original = self.get_proposal(proposal_id)
            if validate_review is not None:
                validate_review()
            self._check_review(expected_review, original, project, session, action="rollback")
            head, before = self._capture_head(project, session)
            applied = self.store.operation_for_proposal(proposal_id)
            if (
                applied is None
                or applied.status != "committed"
                or applied.committed_version != head.revision
            ):
                raise _conflict("Rollback requires the exact currently applied proposal.")
            version = self.store.get_version(project.project_id, head.revision)
            if version.operation_id != applied.operation_id:
                raise _conflict("The selected proposal does not own the current version.")
            target = self.store.get_tree(original.before_tree_sha256)
            old = {item.path: item for item in before.files}
            restored = {item.path: item for item in target.files}
            changes: list[FleetPatchFileChange] = []
            for change in sorted(original.patch.changes, key=lambda item: item.path):
                path = change.path.removeprefix(".fleet/")
                current_file, prior_file = old.get(path), restored.get(path)
                changes.append(
                    FleetPatchFileChange(
                        operation=(
                            FleetPatchOperation.REMOVE
                            if prior_file is None
                            else FleetPatchOperation.ADD
                            if current_file is None
                            else FleetPatchOperation.REPLACE
                        ),
                        path=change.path,
                        before_sha256=current_file.sha256 if current_file else None,
                        after_sha256=prior_file.sha256 if prior_file else None,
                        content=prior_file.content if prior_file else None,
                    )
                )
            patch = FleetPatch(
                fleet_patch_id=self.ids.new(IdPrefix.FLEET_PATCH),
                project_id=project.project_id,
                base_fleet_spec_sha256=head.config_snapshot_sha256,
                changes=changes,
                rationale=f"Explicit user rollback of current proposal {proposal_id}.",
                rollback_of=proposal_id,
            )
            after = evolve_tree(before, patch, rollback_target=target)
            text_diff, semantic_changes = describe_fleet_patch(
                before, after, patch, rollback_target=target
            )
            record = FleetPatchProposalRecord(
                patch=patch,
                source_run_id=original.source_run_id,
                base=head.admission,
                before_tree_sha256=before.sha256,
                after_tree_sha256=after.sha256,
                before_config_snapshot_sha256=head.config_snapshot_sha256,
                after_config_snapshot_sha256=self.config.snapshot_hash(self._snapshot(after)),
                text_diff=text_diff,
                semantic_changes=semantic_changes,
                created_at=self.clock.now(),
            )
            proposal = self.store.save_proposal(record, before, after)
            self.record_proposal_artifacts(proposal, self.state.get_run(original.source_run_id))
            return self._publish(
                project, proposal, session, operation_id=operation_id, authorization="rollback"
            )

    def recover(
        self, operation_id: str, *, owner_stopped: bool = False
    ) -> OrganizationPublicationResult:
        if owner_stopped is not True:
            raise FleetError(
                ErrorCode.APPROVAL_REQUIRED,
                "Publication recovery requires confirmation that its original owner stopped.",
                "Stop the original publisher, then use fleet fleet-patch recover "
                "with --owner-stopped.",
            )
        operation = self.get_operation(operation_id)
        with self.files.session(operation.project_before, operation_id) as session:
            operation = self.get_operation(operation_id)
            proposal = self.get_proposal(operation.proposal_id)
            head = self.store.get_head(operation.base.project_id)
            if operation.status in {"committed", "aborted"}:
                expected_revision = (
                    operation.committed_version
                    if operation.status == "committed"
                    else operation.base.revision
                )
                if (
                    head is None
                    or head.revision != expected_revision
                    or head.pending_operation_id is not None
                ):
                    raise _recovery_error(operation_id)
                version = (
                    self.store.get_version(operation.base.project_id, expected_revision or 0)
                    if operation.status == "committed"
                    else None
                )
                return self._cleanup_result(operation, proposal, session, version, changed=False)
            if (
                head is None
                or head.pending_operation_id != operation_id
                or self.state.get_project(operation.base.project_id) != operation.project_before
            ):
                raise _recovery_error(operation_id)
            try:
                boundary = self.repository.inspect_organization_boundary(
                    Path(operation.project_before.canonical_root)
                )
                if not operation.repository_before.unchanged_outside_organization(boundary):
                    raise _recovery_error(operation_id)
                observation = session.observe(operation.publication)
                if observation.state == "prepared":
                    if boundary != operation.repository_before:
                        raise _recovery_error(operation_id)
                    aborted = self.store.abort_operation(operation_id, observation)
                    if (
                        self.store.get_operation(operation_id) != aborted
                        or aborted.status != "aborted"
                    ):
                        raise _recovery_error(operation_id)
                    return self._cleanup_result(aborted, proposal, session, None, changed=False)
                if observation.state != "exchanged":
                    raise _recovery_error(operation_id)
                observation = session.sync_exchanged(operation.publication)
                version = self._commit(operation, proposal, session, observation)
            except BaseException:
                self._retain_recovery(operation_id)
                failure = _recovery_error(operation_id)
            else:
                return self._cleanup_result(
                    self.store.get_operation(operation_id), proposal, session, version, changed=True
                )
        raise failure from None

    def _publish(
        self,
        project: Project,
        proposal: FleetPatchProposalRecord,
        session: OrganizationPublicationSession,
        *,
        operation_id: str,
        authorization: Literal["apply", "rollback"],
    ) -> OrganizationPublicationResult:
        # The second check is under the cross-state lock, not only CLI preflight.
        existing = self.store.operation_for_proposal(proposal.patch.fleet_patch_id)
        if existing is not None:
            return self._repeat(existing)
        head, before = self._capture_head(project, session)
        if proposal.base != head.admission or proposal.before_tree_sha256 != before.sha256:
            raise _conflict("The reviewed proposal belongs to an older organization generation.")
        after = self.store.get_tree(proposal.after_tree_sha256)
        self._snapshot(after)
        boundary = self.repository.inspect_organization_boundary(Path(project.canonical_root))
        if (
            boundary.repository.root != project.canonical_root
            or boundary.repository.identity_hash != project.identity_hash
            or boundary.non_organization_status_sha256 != canonical_json_hash([])
            or (
                boundary.repository.status_porcelain
                and boundary.repository.status_fingerprint != project.init_status_fingerprint
            )
        ):
            raise _conflict(
                "The repository contains changes outside the reviewed organization allowance."
            )
        # The native session owns the operation ID even before staging yields a receipt.
        failure: FleetError | None
        try:
            prepared = session.stage(after)
        except BaseException:
            failure = FleetError(
                ErrorCode.RECOVERY_REQUIRED,
                "Organization staging failed before a durable publication receipt existed.",
                "The target was not exchanged. Preserve and inspect any private .fleet-publication "
                "scratch beside the repository; unrecorded scratch cannot be "
                "automatically recovered.",
                details={
                    "operation_id": operation_id,
                    "scratch_basename": ".fleet-publication-" + operation_id,
                    "journaled": False,
                },
            )
        else:
            failure = None
        if failure is not None:
            raise failure from None
        try:
            if prepared.operation_id != operation_id:
                raise _recovery_error(operation_id)
            if (
                self.repository.inspect_organization_boundary(Path(project.canonical_root))
                != boundary
            ):
                raise _conflict("The repository changed during organization staging.")
            operation = self.store.prepare_operation(
                project,
                proposal.patch.fleet_patch_id,
                prepared,
                authorization=authorization,
                repository_before=boundary,
            )
        except BaseException:
            if self._discard_unprepared(proposal, before, after, session, prepared):
                failure = _conflict(
                    "Publication preparation was rejected; exact staged scratch was cleaned "
                    "and the target was not exchanged."
                )
            else:
                self._retain_recovery(prepared.operation_id)
                failure = _recovery_error(prepared.operation_id)
        else:
            failure = None
        if failure is not None:
            raise failure from None
        try:
            observation = session.exchange(prepared)
            version = self._commit(operation, proposal, session, observation)
        except BaseException:
            self._retain_recovery(prepared.operation_id)
            failure = _recovery_error(prepared.operation_id)
        else:
            return self._cleanup_result(
                self.store.get_operation(prepared.operation_id),
                proposal,
                session,
                version,
                changed=True,
            )
        raise failure from None

    def _commit(
        self,
        operation: OrganizationOperation,
        proposal: FleetPatchProposalRecord,
        session: OrganizationPublicationSession,
        observation: PublicationObservation,
    ) -> OrganizationVersion:
        after = session.capture_target()
        if after.sha256 != proposal.after_tree_sha256:
            raise _recovery_error(operation.operation_id)
        snapshot = self._snapshot(after)
        boundary = self.repository.inspect_organization_boundary(
            Path(operation.project_before.canonical_root)
        )
        if not operation.repository_before.unchanged_outside_organization(boundary):
            raise _recovery_error(operation.operation_id)
        snapshot_artifact = self.artifacts.create_text(
            kind=ArtifactKind.CONFIG_SNAPSHOT,
            project_id=operation.base.project_id,
            producer="control-plane",
            content=snapshot.model_dump_json(indent=2),
            mime_type="application/json",
            redact=False,
            reject_secret=True,
            metadata={"organization_operation_id": operation.operation_id},
        )
        if (
            snapshot_artifact.sha256 != proposal.after_config_snapshot_sha256
            or self.artifacts.read_text(snapshot_artifact.artifact_id)
            != snapshot.model_dump_json(indent=2)
        ):
            raise _recovery_error(operation.operation_id)
        updated = operation.project_before.model_copy(
            update={
                "fleet_spec_hash": proposal.after_config_snapshot_sha256,
                "config_snapshot_artifact_id": snapshot_artifact.artifact_id,
                "init_status_fingerprint": boundary.repository.status_fingerprint,
                "updated_at": self.clock.now(),
            }
        )
        # Recheck after artifact I/O and immediately before the durable CAS.
        if (
            session.capture_target() != after
            or self.repository.inspect_organization_boundary(Path(updated.canonical_root))
            != boundary
        ):
            raise _recovery_error(operation.operation_id)
        version = self.store.commit_operation(operation.operation_id, updated, observation)
        committed = self.store.get_operation(operation.operation_id)
        if (
            committed.status != "committed"
            or committed.committed_version != version.version
            or self.store.get_version(updated.project_id, version.version) != version
            or self.state.get_project(updated.project_id) != updated
        ):
            raise _recovery_error(operation.operation_id)
        return version

    def _discard_unprepared(
        self,
        proposal: FleetPatchProposalRecord,
        before: OrganizationTree,
        after: OrganizationTree,
        session: OrganizationPublicationSession,
        prepared: PreparedPublication,
    ) -> bool:
        try:
            if self.store.operation_for_proposal(proposal.patch.fleet_patch_id) is not None:
                return False
            head = self.store.assert_current(proposal.base)
            if (
                head.pending_operation_id is not None
                or session.observe(prepared).state != "prepared"
            ):
                return False
            session.cleanup_owned(
                prepared,
                expected_target_sha256=before.sha256,
                expected_backup_sha256=after.sha256,
                expected_backup_tree=after,
            )
            return True
        except BaseException:
            # No authoritative absence/cleanup proof: retain everything, report uncertainty.
            return False

    def _retain_recovery(self, operation_id: str) -> None:
        try:
            operation = self.store.get_operation(operation_id)
            if operation.status == "prepared":
                self.store.require_recovery(operation_id)
        except BaseException:
            # Failure reporting must not guess whether a durable commit happened.
            # The persisted PREPARED fence remains sufficient when re-read is unavailable.
            return

    def _repeat(self, operation: OrganizationOperation) -> OrganizationPublicationResult:
        if operation.status != "committed" or operation.committed_version is None:
            raise _recovery_error(operation.operation_id)
        version = self.store.get_version(operation.base.project_id, operation.committed_version)
        return OrganizationPublicationResult(
            proposal_id=operation.proposal_id,
            operation_id=operation.operation_id,
            status="committed",
            version=version,
            changed=False,
            cleanup_complete=None,
            warnings=(
                "Original committed result returned; historical scratch was not "
                "inspected or modified.",
            ),
        )

    def _cleanup_result(
        self,
        operation: OrganizationOperation,
        proposal: FleetPatchProposalRecord,
        session: OrganizationPublicationSession,
        version: OrganizationVersion | None,
        *,
        changed: bool,
    ) -> OrganizationPublicationResult:
        if operation.status not in {"committed", "aborted"}:
            raise _recovery_error(operation.operation_id)
        target_sha = (
            proposal.after_tree_sha256 if version is not None else proposal.before_tree_sha256
        )
        backup_sha = (
            proposal.before_tree_sha256 if version is not None else proposal.after_tree_sha256
        )
        complete = False
        try:
            backup = self.store.get_tree(backup_sha)
            session.cleanup_owned(
                operation.publication,
                expected_target_sha256=target_sha,
                expected_backup_sha256=backup_sha,
                expected_backup_tree=backup,
            )
            complete = True
        except BaseException:
            # The version already has authoritative read-back. Report the separate cleanup gap.
            pass
        return OrganizationPublicationResult(
            proposal_id=operation.proposal_id,
            operation_id=operation.operation_id,
            status="committed" if version is not None else "aborted",
            version=version,
            changed=changed,
            cleanup_complete=complete,
            warnings=()
            if complete
            else (
                "Exact scratch cleanup is incomplete; stop the publisher and recover "
                f"{operation.operation_id}.",
            ),
        )

    def _register_secrets(self, *references: str | None) -> None:
        for reference in dict.fromkeys(references):
            if reference is None:
                continue
            try:
                value = self.secrets.resolve(reference)
            except SecretNotConfiguredError:
                continue
            except SecretStoreError:
                raise FleetError(
                    ErrorCode.CREDENTIAL_INVALID,
                    "A recorded provider credential could not be registered for safe inspection.",
                    "Correct the explicit stored credential reference; no model call was made.",
                ) from None
            del value

    def register_project_secrets(self, project: Project) -> None:
        if self.model_profiles is not None:
            self.model_profiles.prepare_project(project)
        else:
            self._register_secrets(project.credential_ref)

    def register_run_secrets(self, run: Run) -> None:
        project = self.state.get_project(run.project_id)
        if run.model_bindings_sha256 is None:
            self._register_secrets(project.credential_ref, run.credential_ref)
        elif self.model_profiles is None:
            raise _conflict("The required model-binding service is unavailable.")
        else:
            self.model_profiles.inspect_bindings(
                project,
                root_run_id=run.parent_run_id or run.run_id,
                expected_sha256=run.model_bindings_sha256,
            )

    @contextmanager
    def initialization_guard(self, project: Project, *, expected: Project | None) -> Iterator[None]:
        """Fence all init filesystem/Project writes without creating a version baseline."""
        with self.files.session(project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)):
            current = self.state.get_project_by_root(project.canonical_root)
            if current != expected:
                raise _conflict("Project registration changed during initialization preflight.")
            if current is not None and self.store.get_head(current.project_id) is not None:
                raise _conflict(
                    "An organization with admitted Run history cannot be reinitialized; "
                    "use a reviewed FleetPatch for supported changes."
                )
            yield

    @contextmanager
    def admission(
        self, project: Project, *, expected: OrganizationAdmission | None = None
    ) -> Iterator[OrganizationAdmission]:
        """Keep the cross-state publication lock across final recheck and Run insertion."""
        with self.files.session(project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)) as session:
            head, _ = self._capture_head(project, session)
            if expected is not None and expected != head.admission:
                raise _conflict("The organization changed after execution preflight.")
            yield head.admission

    @contextmanager
    def run_guard(self, run: Run) -> Iterator[None]:
        """Serialize configuration-dependent continuation/application with publication."""
        project = self.state.get_project(run.project_id)
        self.register_run_secrets(run)
        with self.files.session(project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)) as session:
            head, _ = self._capture_head(project, session)
            admitted = self.store.admission_for_run(run.run_id)
            if admitted is None:
                if head.revision != 0:
                    raise _conflict("A legacy Run cannot continue after organization evolution.")
            elif admitted != head.admission:
                raise _conflict("The Run belongs to an older organization generation.")
            if run.config_snapshot_hash != head.config_snapshot_sha256:
                raise _conflict("The Run configuration no longer matches the organization.")
            yield

    def proposal_context(self, run: Run, snapshot: ConfigSnapshot) -> EvolutionContext:
        project = self.state.get_project(run.project_id)
        with self.files.session(project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)) as session:
            head, tree = self._capture_head(project, session)
            admitted = self.store.admission_for_run(run.run_id)
            if (
                admitted != head.admission
                or self.config.snapshot_hash(snapshot) != head.config_snapshot_sha256
            ):
                raise _conflict("CoS proposal context does not match its admitted Run.")
            return build_evolution_context(
                tree, admitted, self.ids.new(IdPrefix.FLEET_PATCH), self.redactor
            )

    def propose(
        self, run: Run, patch: FleetPatch, context: EvolutionContext
    ) -> FleetPatchProposalRecord:
        validate_context_proposal(patch, context, self.redactor)
        if len(patch.model_dump_json(indent=2).encode("utf-8")) > MAX_PROPOSAL_ARTIFACT_BYTES:
            raise _conflict("The proposal exceeds the inspectable artifact byte ceiling.")
        project = self.state.get_project(run.project_id)
        with self.files.session(project, self.ids.new(IdPrefix.ORGANIZATION_OPERATION)) as session:
            head, before = self._capture_head(project, session)
            if (
                head.admission != context.admission
                or self.store.admission_for_run(run.run_id) != head.admission
            ):
                raise _conflict("The proposal is stale for the current organization.")
            after = evolve_tree(before, patch)
            after_snapshot = self._snapshot(after)
            text_diff, semantic_changes = describe_fleet_patch(before, after, patch)
            record = FleetPatchProposalRecord(
                patch=patch,
                source_run_id=run.run_id,
                base=head.admission,
                before_tree_sha256=before.sha256,
                after_tree_sha256=after.sha256,
                before_config_snapshot_sha256=head.config_snapshot_sha256,
                after_config_snapshot_sha256=self.config.snapshot_hash(after_snapshot),
                text_diff=text_diff,
                semantic_changes=semantic_changes,
                created_at=self.clock.now(),
            )
            return self.store.save_proposal(record, before, after)

    def record_proposal_artifacts(self, proposal: FleetPatchProposalRecord, run: Run) -> None:
        if run.task_id is None or proposal.source_run_id != run.run_id:
            raise _conflict("Proposal artifacts need their exact delivering TaskSpec.")
        for kind, content, mime in (
            (
                ArtifactKind.FLEET_PATCH,
                proposal.patch.model_dump_json(indent=2),
                "application/json",
            ),
            (ArtifactKind.FLEET_PATCH_DIFF, proposal.text_diff, "text/x-diff"),
        ):
            self.artifacts.create_text(
                kind=kind,
                project_id=run.project_id,
                run_id=run.run_id,
                task_id=run.task_id,
                producer="control-plane",
                content=content,
                mime_type=mime,
                redact=False,
                reject_secret=True,
                metadata={
                    "fleet_patch_id": proposal.patch.fleet_patch_id,
                    "proposal_sha256": proposal.proposal_sha256,
                },
            )

    def _capture_head(
        self, project: Project, session: OrganizationPublicationSession
    ) -> tuple[OrganizationHead, OrganizationTree]:
        current = self.state.get_project(project.project_id)
        if current != project:
            raise _conflict("The registered project changed during organization preflight.")
        tree = session.capture_target()
        snapshot = self._snapshot(tree)
        config_hash = self.config.snapshot_hash(snapshot)
        if config_hash != project.fleet_spec_hash:
            raise _conflict("The organization differs from the reviewed project configuration.")
        head = self.store.get_head(project.project_id)
        if head is None:
            head = self.store.register_baseline(project, tree, config_hash)
        head = self.store.assert_current(head.admission)
        if (
            head.tree_sha256 != tree.sha256
            or head.config_snapshot_sha256 != config_hash
            or head.project_sha256 != canonical_json_hash(project.model_dump(mode="json"))
        ):
            raise _conflict("The complete organization tree or project binding has drifted.")
        return head, tree

    def _snapshot(self, tree: OrganizationTree) -> ConfigSnapshot:
        if self.redactor.contains_secret_data(tree.model_dump(mode="json")):
            raise _conflict("The organization contains a registered secret.")
        return self.config.snapshot_from_files({item.path: item.content for item in tree.files})[1]


def _conflict(message: str) -> FleetError:
    return FleetError(
        ErrorCode.CONFIG_INVALID,
        message,
        "Inspect the organization version and pending operations; do not replay stale work.",
    )


def _recovery_error(operation_id: str) -> FleetError:
    return FleetError(
        ErrorCode.RECOVERY_REQUIRED,
        "Organization publication requires exact stopped-owner reconciliation; "
        "its outcome is not assumed.",
        f"Stop the original publisher, then inspect and recover {operation_id}; "
        "do not reapply or reverse it manually.",
        details={"operation_id": operation_id},
    )
