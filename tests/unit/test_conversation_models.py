from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_fleet.domain.conversation import (
    Conversation,
    ConversationArtifactRef,
    ConversationContext,
    ConversationContextEntry,
    ConversationSubmission,
    ConversationSummary,
)
from agent_fleet.domain.models import ArtifactKind, RunStatus


def _entry(sequence: int = 1) -> ConversationContextEntry:
    return ConversationContextEntry(
        turn_id=f"turn_{sequence:032x}",
        sequence=sequence,
        run_id=f"run_{sequence:032x}",
        run_status=RunStatus.READY_FOR_REVIEW,
        user_summary=ConversationSummary(text="Requested work"),
        result_summary=ConversationSummary(text="Delivered an unverified review candidate"),
    )


def test_context_is_frozen_portable_and_explicit_about_omissions() -> None:
    context = ConversationContext(
        conversation_id="conv_" + "1" * 32,
        project_id="prj_" + "1" * 32,
        through_sequence=10,
        entries=(_entry(9), _entry(10)),
    )
    assert context.omitted_turn_count == 8
    assert ConversationContext.model_validate_json(context.model_dump_json()) == context
    assert len(context.context_sha256) == 64
    with pytest.raises(ValidationError):
        context.through_sequence = 11  # type: ignore[misc]


@pytest.mark.parametrize("text", ["", " ", "\x00", "界" * 1366, "x" * 4097])
def test_summary_enforces_utf8_and_nonempty_bounds(text: str) -> None:
    with pytest.raises(ValidationError):
        ConversationSummary(text=text)


@pytest.mark.parametrize(
    "timestamp", [datetime(2026, 1, 1), datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))]
)
def test_conversation_timestamps_require_actual_utc(timestamp: datetime) -> None:
    with pytest.raises(ValidationError):
        Conversation(
            conversation_id="conv_" + "1" * 32,
            project_id="prj_" + "1" * 32,
            repository_identity="1" * 64,
            created_at=timestamp,
            updated_at=timestamp,
        )


@pytest.mark.parametrize("key", ["", "../escape", "has space", "雪", "x" * 129, "\x00"])
def test_submission_keys_cannot_select_paths_or_unbounded_values(key: str) -> None:
    with pytest.raises(ValidationError):
        ConversationSubmission(
            conversation_id="conv_" + "1" * 32,
            project_id="prj_" + "1" * 32,
            repository_identity="1" * 64,
            submission_key=key,
            expected_revision=0,
            context=ConversationContext(
                conversation_id="conv_" + "1" * 32, project_id="prj_" + "1" * 32, through_sequence=0
            ),
            user_summary=ConversationSummary(text="Test"),
        )


@pytest.mark.parametrize("entries", [(_entry(), _entry()), (_entry(2), _entry()), (_entry(4),)])
def test_context_rejects_duplicates_reordering_and_future_turns(
    entries: tuple[ConversationContextEntry, ...],
) -> None:
    with pytest.raises(ValidationError):
        ConversationContext(
            conversation_id="conv_" + "1" * 32,
            project_id="prj_" + "1" * 32,
            through_sequence=3,
            entries=entries,
        )


def test_context_has_strict_aggregate_byte_and_entry_ceiling() -> None:
    entries = tuple(
        _entry(i).model_copy(
            update={
                "user_summary": ConversationSummary(text="u" * 2048),
                "result_summary": ConversationSummary(text="r" * 4096),
            }
        )
        for i in range(1, 9)
    )
    with pytest.raises(ValidationError, match="32768"):
        ConversationContext(
            conversation_id="conv_" + "1" * 32,
            project_id="prj_" + "1" * 32,
            through_sequence=8,
            entries=entries,
        )
    with pytest.raises(ValidationError):
        ConversationContext(
            conversation_id="conv_" + "1" * 32,
            project_id="prj_" + "1" * 32,
            through_sequence=9,
            entries=tuple(_entry(i) for i in range(1, 10)),
        )


def test_context_cannot_claim_unsettled_execution_or_tool_transcript_authority() -> None:
    with pytest.raises(ValidationError):
        ConversationContextEntry.model_validate(
            _entry().model_dump() | {"run_status": RunStatus.RUNNING}
        )
    with pytest.raises(ValidationError):
        ConversationArtifactRef(
            artifact_id="art_" + "1" * 32,
            run_id="run_" + "1" * 32,
            sha256="1" * 64,
            kind=ArtifactKind.COMMAND_TRANSCRIPT,
        )
    value = ConversationSummary(text="No execution authority")
    with pytest.raises(ValidationError):
        ConversationSummary.model_validate(value.model_dump() | {"permission_grant": "allow"})


def test_revision_and_flags_reject_bool_or_string_coercion() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        Conversation(
            conversation_id="conv_" + "1" * 32,
            project_id="prj_" + "1" * 32,
            repository_identity="1" * 64,
            revision=True,
            created_at=now,
            updated_at=now,
        )
    with pytest.raises(ValidationError):
        ConversationSummary.model_validate({"text": "bounded", "truncated": "false"})
