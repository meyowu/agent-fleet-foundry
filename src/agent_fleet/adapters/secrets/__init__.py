"""Built-in control-plane secret-store adapters."""

from agent_fleet.adapters.secrets.environment import EnvironmentSecretStore

__all__ = ["EnvironmentSecretStore"]
