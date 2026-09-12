"""Replay named release security cases; Docker is separate explicit operator authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

_OFFLINE = (
    "tests/unit/test_paths.py",
    "tests/unit/test_path_security.py",
    "tests/unit/test_bootstrap_security.py",
    "tests/unit/test_permission_policy_security.py",
    "tests/unit/test_runtime_tools.py",
    "tests/unit/test_dispatch_claims.py",
    "tests/unit/test_fleet_patch.py",
    "tests/unit/test_organization_tree.py",
    "tests/contract/test_trust_store.py",
    "tests/contract/test_docker_sandbox.py",
    "tests/contract/test_pydantic_ai_runtime.py",
    "tests/contract/test_organization_publication.py",
    "tests/contract/test_organization_journal.py",
    "tests/integration/test_security_gateway.py",
    "tests/integration/test_gateway_concurrency.py",
    "tests/integration/test_bootstrap_report.py",
    "tests/integration/test_fleet_patch_recovery.py",
    "tests/e2e/test_fleet_evolution_cli.py",
)
_LINUX_DARWIN_SKIPS = {
    "test_real_host_unsupported_metadata_is_retained_and_rejected[xattr]",
    "test_real_host_unsupported_metadata_is_retained_and_rejected[acl]",
    "test_real_host_unsupported_metadata_is_retained_and_rejected[flag]",
    "test_unreproducible_requested_metadata_fails_before_exchange",
    "test_changed_backup_xattr_is_not_normalized_or_deleted_during_cleanup",
}
_BASELINE_COHORT_ENV = "AGENT_FLEET_BASELINE_COHORT_IMAGE"
_BASELINE_COHORT_TEST = "tests/docker/test_business_baseline_cohort.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, required=True, help="New directory under a test-safe parent"
    )
    parser.add_argument("--docker", action="store_true")
    parser.add_argument(
        "--image", help="Explicit already-local runner image; never pulled by this script"
    )
    parser.add_argument(
        "--baseline-cohort-image",
        help="Explicit already-local Python/Node cohort image; never pulled by this script",
    )
    args = parser.parse_args()
    if args.docker != bool(args.image):
        parser.error("--docker and --image must be supplied together")
    if args.baseline_cohort_image is not None and not args.baseline_cohort_image.strip():
        parser.error("--baseline-cohort-image must be non-empty")
    if args.baseline_cohort_image is not None and not (args.docker and args.image):
        parser.error("--baseline-cohort-image requires --docker and --image")
    output = args.output
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or not output.parent.is_dir()
    ):
        parser.error("output must be a new absolute directory with an existing parent")
    output.mkdir(mode=0o700)
    root = Path(__file__).resolve().parents[1]
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
    }
    environment.update(
        {
            "AGENT_FLEET_ENABLE_LIVE_PROVIDER_TESTS": "0",
            "AGENT_FLEET_ENABLE_INSTALL_TESTS": "0",
            "AGENT_FLEET_ENABLE_DOCKER_TESTS": "1" if args.docker else "0",
        }
    )
    baseline_cohort_selected = args.baseline_cohort_image is not None
    excluded_test_paths: list[str] = []
    selection = ["-m", "docker_integration", "tests/docker"] if args.docker else list(_OFFLINE)
    if args.docker and not baseline_cohort_selected:
        excluded_test_paths.append(_BASELINE_COHORT_TEST)
        selection.append(f"--ignore={_BASELINE_COHORT_TEST}")
    if args.image:
        environment["AGENT_FLEET_DOCKER_TEST_IMAGE"] = args.image
    if args.baseline_cohort_image is not None:
        environment[_BASELINE_COHORT_ENV] = args.baseline_cohort_image
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            *selection,
            f"--basetemp={output / 'fixtures'}",
            f"--junitxml={output / 'results.xml'}",
        ],
        cwd=root,
        env=environment,
        check=False,
        timeout=1200,
    )
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    expected_platform_skips: list[str] = []
    unexpected_skips: list[str] = []
    if (output / "results.xml").exists():
        results = ET.parse(output / "results.xml").getroot()
        for suite in results.iter("testsuite"):
            for key in counts:
                counts[key] += int(suite.attrib.get(key, "0"))
        for case in results.iter("testcase"):
            if case.find("skipped") is None:
                continue
            name = case.attrib.get("name", "")
            if (
                sys.platform == "linux"
                and not args.docker
                and case.attrib.get("classname") == "tests.contract.test_organization_publication"
                and name in _LINUX_DARWIN_SKIPS
            ):
                expected_platform_skips.append(name)
            else:
                unexpected_skips.append(name)
    verdict = result.returncode or (
        1
        if counts["tests"] == 0 or counts["errors"] or counts["failures"] or unexpected_skips
        else 0
    )
    sources = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in ("src", "tests", "scripts")
        for path in sorted(root.joinpath(directory).rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    }
    report = {
        "schema_version": 1,
        "mode": "docker" if args.docker else "offline",
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "exit_code": verdict,
        "pytest_exit_code": result.returncode,
        "expected_platform_skips": expected_platform_skips,
        "unexpected_skips": unexpected_skips,
        "baseline_cohort_selected": baseline_cohort_selected,
        "excluded_test_paths": excluded_test_paths,
        "selection": selection,
        "counts": counts,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(sources, sort_keys=True).encode()
        ).hexdigest(),
        "live_provider_executed": False,
        "limits": (
            "Named automated adversarial replay; not a hostile-host or human penetration audit."
        ),
    }
    (output / "evidence.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(verdict)


if __name__ == "__main__":
    main()
