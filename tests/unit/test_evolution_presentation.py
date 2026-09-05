from __future__ import annotations

import json

from pydantic import JsonValue

from agent_fleet.cli.evolution import _detail_view, _visible_diff


def test_human_proposal_diff_cannot_execute_terminal_controls() -> None:
    raw = "+ [bold]literal[/bold]\n\t\x1b]52;c;payload\x07\x7f\r"
    visible = _visible_diff(raw)
    assert "\x1b" not in visible and "\x07" not in visible and "\r" not in visible
    assert visible == "+ [bold]literal[/bold]\n\t\\x1b]52;c;payload\\x07\\x7f\\x0d"


def test_human_detailed_record_is_plain_json_while_machine_data_is_exact() -> None:
    raw: dict[str, JsonValue] = {"text_diff": "\x1b]52;c;payload\x07[link=x]literal[/link]"}
    human = _detail_view(raw, json_output=False)
    assert isinstance(human, dict) and isinstance(human["display"], str)
    assert "\x1b" not in human["display"] and json.loads(human["display"]) == raw
    assert _detail_view(raw, json_output=True) == raw
