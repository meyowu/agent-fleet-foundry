"""Deterministic fixture payloads for the offline orchestration canary."""

BOOTSTRAP_HOST_SENTINEL_NAME = "outside-workspace-sentinel"
BOOTSTRAP_SANDBOX_PROBE_MARKER = "AGENT_FLEET_SANDBOX_BOUNDARY_OK"

BROKEN_CANARY = '''"""Tiny deterministic canary."""


def divide(a: float, b: float) -> float:
    return a / b
'''

FIXED_CANARY = '''"""Tiny deterministic canary."""


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("division by zero is not allowed")
    return a / b
'''

INCORRECT_CANARY = '''"""Tiny deterministic canary."""


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("wrong message")
    return a / b
'''
