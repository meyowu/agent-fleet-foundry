from __future__ import annotations

import pytest

from agent_fleet.domain.paths import path_is_within, path_overlaps_scope


@pytest.mark.parametrize("path", ["src", "src/a.py", "src/nested/a.py", "SRC/a.py"])
def test_scope_includes_only_exact_or_descendants(path: str) -> None:
    assert path_is_within(path, ["src"])


@pytest.mark.parametrize("path", [".", "src2/a.py", "a/src", "srcx", "tests/a.py"])
def test_scope_does_not_widen_to_parents_or_prefixes(path: str) -> None:
    assert not path_is_within(path, ["src"])


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/src",
        "src/",
        "src//a",
        "src/./a",
        "src/../a",
        "src\\a",
        "src/\na",
        "src/\x00a",
        "src/\udcff",
    ],
)
def test_noncanonical_paths_fail_closed(path: str) -> None:
    assert not path_is_within(path, ["."])
    assert not path_overlaps_scope(path, ["."])


def test_forbidden_descendant_intersection_is_not_mutation_authority() -> None:
    for path in ("src/private", "src/private/a", "src", "."):
        assert not path_is_within(path, ["."], forbidden=["src/private"])
    assert path_is_within("src/public/a", ["."], forbidden=["src/private"])


def test_observation_traverses_parents_but_filters_forbidden_children() -> None:
    assert path_overlaps_scope(".", ["src/public"], forbidden=["src/private"])
    assert path_overlaps_scope("src", ["src/public"], forbidden=["src/private"])
    assert not path_overlaps_scope("src/private", ["src"], forbidden=["src/private"])
    assert not path_overlaps_scope("src2", ["src"])


def test_bad_policy_scope_fails_closed_without_normalizing_it() -> None:
    assert not path_is_within("src/a", ["src", "bad/../scope"])
    assert not path_overlaps_scope("src/a", ["src"], forbidden=["bad//scope"])
