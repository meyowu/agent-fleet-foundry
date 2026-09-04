"""Generate deterministic JSON Schemas from canonical Pydantic models."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel

from agent_fleet.domain.config import FleetSpec, VerificationProfile
from agent_fleet.domain.models import JsonEnvelope, TaskSpec, ToolIntent, VerifierVerdict

SCHEMAS: dict[str, type[BaseModel]] = {
    "fleet.schema.json": FleetSpec,
    "verification-profile.schema.json": VerificationProfile,
    "cli-envelope.schema.json": JsonEnvelope,
    "task-spec.schema.json": TaskSpec,
    "tool-intent.schema.json": ToolIntent,
    "verifier-verdict.schema.json": VerifierVerdict,
}


def rendered_schemas() -> dict[str, str]:
    return {
        name: json.dumps(model.model_json_schema(), indent=2, sort_keys=True) + "\n"
        for name, model in SCHEMAS.items()
    }


def generate(output: Path, *, check: bool) -> int:
    mismatches: list[str] = []
    for name, content in rendered_schemas().items():
        destination = output / name
        if check:
            if not destination.exists() or destination.read_text(encoding="utf-8") != content:
                mismatches.append(name)
        else:
            output.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
    if mismatches:
        raise SystemExit(f"generated schemas differ: {', '.join(mismatches)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    return generate(args.output, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
