"""Exact provider identifiers and side-effect-free client-admission checks."""

import logging
import os


def parse_provider_model(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    provider, separator, model = value.partition(":")
    if (
        separator != ":"
        or provider not in {"openai", "openai-chat", "anthropic", "google"}
        or not model
    ):
        return None
    return provider, model


def provider_policy_issue(provider: str) -> str | None:
    """Never read an environment value, credential, config file or SDK here."""
    if provider in {"openai", "openai-chat"}:
        if "OPENAI_CUSTOM_HEADERS" in os.environ:
            return "Ambient OpenAI custom headers are not permitted for the BYOK runtime."
    elif provider == "anthropic":
        if any(name in os.environ for name in ("ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_LOG")):
            return "Ambient Anthropic header or logging customization is not permitted."
        # Installed httpx2 uses httpcore2. Both SDK DEBUG and HTTP INFO/DEBUG
        # records can contain untrusted data before response hooks. A child logger
        # may override its parent's level; inspect configured descendants too.
        namespaces = ("anthropic", "httpx2", "httpcore2")
        names = set(namespaces) | {
            name
            for name in logging.Logger.manager.loggerDict
            if any(name.startswith(prefix + ".") for prefix in namespaces)
        }
        if any(logging.getLogger(name).isEnabledFor(logging.INFO) for name in names):
            return "Verbose provider transport logging is not permitted for Anthropic BYOK."
    elif provider == "google":
        # Importing this Fleet module does not import the optional Google SDK.
        from agent_fleet.adapters.runtime.google_provider import require_google_policy
        from agent_fleet.domain.errors import FleetError

        try:
            require_google_policy()
        except FleetError:
            return "Ambient Google replay or verbose transport logging is not permitted."
    return None
