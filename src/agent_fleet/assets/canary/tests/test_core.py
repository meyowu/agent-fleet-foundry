import pytest
from canary_calc.core import divide


@pytest.mark.parametrize(("a", "b", "expected"), [(6, 2, 3), (-6, 2, -3), (0, 2, 0), (1, 2, 0.5)])
def test_normal_division(a: float, b: float, expected: float) -> None:
    assert divide(a, b) == expected


def test_zero_division_has_actionable_error() -> None:
    with pytest.raises(ValueError, match="division by zero is not allowed"):
        divide(1, 0)
