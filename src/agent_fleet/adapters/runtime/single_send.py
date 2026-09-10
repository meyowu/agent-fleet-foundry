"""A single physical send per already budgeted model request, never a retry budget."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from pydantic_ai import ModelSettings
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.profiles import ToolAdditionMode, ToolDeferralMode

from agent_fleet.domain.errors import ErrorCode, FleetError


def send_policy_error() -> FleetError:
    return FleetError(
        ErrorCode.PROVIDER_FAILED,
        "The provider request violated the pinned single-send transport policy.",
        "Inspect the retained request accounting; no implicit retry is authorized.",
        details={
            "runtime_diagnostic": {
                "category": "provider_sdk",
                "cause_category": "request_policy",
            }
        },
    )


@dataclass
class _Ticket:
    active: bool = True
    used: bool = False


class SingleSendGate:
    def __init__(self) -> None:
        self._ticket: ContextVar[_Ticket | None] = ContextVar("fleet_provider_send", default=None)

    @contextmanager
    def request(self) -> Iterator[None]:
        if self._ticket.get() is not None:
            raise send_policy_error()
        ticket = _Ticket()
        token = self._ticket.set(ticket)
        try:
            yield
        finally:
            # Child asyncio contexts share the object, not a renewable allowance.
            ticket.active = False
            self._ticket.reset(token)

    def consume(self) -> None:
        ticket = self._ticket.get()
        if ticket is None or not ticket.active or ticket.used:
            raise send_policy_error()
        ticket.used = True


class SingleSendModel(WrapperModel):
    def __init__(
        self, wrapped: Model, gate: SingleSendGate, *, expected_model: str | None = None
    ) -> None:
        super().__init__(wrapped)
        self._gate = gate
        self._expected_model = expected_model

    @property
    def tool_deferral_mode(self) -> ToolDeferralMode | None:
        return self.wrapped.tool_deferral_mode

    @property
    def tool_addition_mode(self) -> ToolAdditionMode | None:
        return self.wrapped.tool_addition_mode

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        with self._gate.request():
            response = await self.wrapped.request(
                messages, model_settings, model_request_parameters
            )
            if self._expected_model is not None and response.model_name != self._expected_model:
                raise FleetError(
                    ErrorCode.PROVIDER_FAILED,
                    "The provider response model did not match the exact selected model.",
                    "Use an exact model version; aliases and implicit fallback are not admitted.",
                    details={
                        "runtime_diagnostic": {
                            "category": "provider_sdk",
                            "cause_category": "response_policy",
                        }
                    },
                )
            return response
