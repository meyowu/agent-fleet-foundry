"""Volatile bytes are decoded/redacted/sanitized before bounded persistence."""

import pytest

from agent_fleet.application.gateway import _baseline_output
from agent_fleet.domain.security import Redactor


@pytest.mark.parametrize("split", [1, 4, 10])
def test_secret_spanning_capture_chunks_is_redacted_before_hashing(split: int) -> None:
    secret = "baseline-private-output"
    raw = (secret[:split].encode(), secret[split:].encode())
    stdout, stderr, replaced, shortened = _baseline_output(b"".join(raw), b"", Redactor([secret]))
    assert secret not in stdout + stderr
    assert stdout == "<redacted:1>"
    assert not replaced and not shortened


def test_invalid_utf8_and_terminal_controls_are_explicit_and_bounded() -> None:
    stdout, stderr, replaced, shortened = _baseline_output(
        b"hello\x1b[31m\xff\r\x00\t\n", b"\x7fend", Redactor()
    )
    assert replaced and not shortened
    assert not any(char in stdout + stderr for char in ("\x1b", "\r", "\x00", "\x7f"))
    assert "\t\n" in stdout
    assert len(stdout.encode()) + len(stderr.encode()) <= 64_000


def test_redaction_expansion_is_rebounded_after_whole_field_redaction() -> None:
    stdout, stderr, replaced, shortened = _baseline_output(
        b"x" * 40_000, b"x" * 24_000, Redactor(["x"])
    )
    assert "x" not in stdout + stderr
    assert not replaced and shortened
    assert len(stdout.encode()) + len(stderr.encode()) <= 64_000
