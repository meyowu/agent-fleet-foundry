"""Six fixed, tiny repositories; business code runs only in optional Docker tests."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class BaselineCase:
    ecosystem: Literal["python", "node"]
    outcome: Literal["passing", "missing_dependency", "preexisting_failure"]

    @property
    def identity(self) -> str:
        return f"{self.ecosystem}-{self.outcome}"

    @property
    def command_id(self) -> str:
        return f"{self.ecosystem}-test"

    @property
    def exit_code(self) -> int:
        if self.outcome == "passing":
            return 0
        return 2 if self.ecosystem == "python" and self.outcome == "missing_dependency" else 1

    @property
    def output_marker(self) -> str:
        if self.outcome == "missing_dependency":
            return "fleet_cohort_deliberately_absent_dependency"
        if self.outcome == "preexisting_failure":
            return "FLEET_COHORT_EXISTING_ASSERTION"
        return "1 passed" if self.ecosystem == "python" else "FLEET_COHORT_PASS"

    def files(self) -> dict[str, str]:
        """Return immutable input definitions without importing/running project code."""
        common = {"README.md": f"Generated baseline fixture: {self.identity}.\n"}
        if self.ecosystem == "python":
            common["pyproject.toml"] = (
                '[project]\nname = "fleet-baseline-fixture"\nversion = "0.0.0"\n'
                'requires-python = ">=3.12"\ndependencies = ["pytest"]\n'
                '[tool.pytest.ini_options]\naddopts = "-p no:cacheprovider"\n'
            )
            if self.outcome == "missing_dependency":
                body = "import fleet_cohort_deliberately_absent_dependency\n"
            else:
                expected = 4 if self.outcome == "passing" else 5
                body = (
                    "import unittest\n\n"
                    "class ArithmeticTest(unittest.TestCase):\n"
                    "    def test_addition(self):\n"
                    f"        self.assertEqual(2 + 2, {expected}, "
                    "'FLEET_COHORT_EXISTING_ASSERTION')\n"
                )
            common["test_business.py"] = body
        else:
            common["package.json"] = (
                json.dumps(
                    {
                        "name": "fleet-baseline-fixture",
                        "version": "0.0.0",
                        "private": True,
                        "type": "module",
                        "packageManager": "npm@10.9.3",
                        "engines": {"node": ">=22"},
                        "scripts": {"test": "node --test"},
                    },
                    indent=2,
                )
                + "\n"
            )
            if self.outcome == "missing_dependency":
                body = "import 'fleet_cohort_deliberately_absent_dependency';\n"
            else:
                expected = 4 if self.outcome == "passing" else 5
                body = (
                    "import test from 'node:test';\n"
                    "import assert from 'node:assert/strict';\n"
                    "test('FLEET_COHORT_PASS', () => {\n"
                    f"  assert.equal(2 + 2, {expected}, 'FLEET_COHORT_EXISTING_ASSERTION');\n"
                    "});\n"
                )
            common["business.test.js"] = body
        return common


CASES = (
    BaselineCase("python", "passing"),
    BaselineCase("python", "missing_dependency"),
    BaselineCase("python", "preexisting_failure"),
    BaselineCase("node", "passing"),
    BaselineCase("node", "missing_dependency"),
    BaselineCase("node", "preexisting_failure"),
)


def fixture_git(repository: Path, *arguments: str) -> str:
    """Only trusted Git operations on a disposable fixture, never its scripts."""
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=repository,
        env={
            "PATH": os.environ.get("PATH", os.defpath),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": "C.UTF-8",
        },
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    return result.stdout


def create_repository(root: Path, case: BaselineCase) -> Path:
    root.mkdir()
    for name, text in case.files().items():
        (root / name).write_text(text, encoding="utf-8")
    fixture_git(root, "init", "--initial-branch=main")
    fixture_git(root, "config", "user.name", "Fleet Baseline Fixture")
    fixture_git(root, "config", "user.email", "baseline@example.invalid")
    fixture_git(root, "add", "--all")
    fixture_git(root, "commit", "-m", "Frozen business baseline fixture")
    return root
