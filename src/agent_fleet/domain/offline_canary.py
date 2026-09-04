"""Deterministic fixture payloads for the offline orchestration canary."""

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
