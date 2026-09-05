# Agent Fleet Python runner v1

This directory is a complete build context shipped in the Fleet wheel and source
distribution. From the activated Fleet environment, locate it with:

```bash
python -c "from importlib.resources import files; print(files('agent_fleet').joinpath('assets/runner'))"
```

Explicitly build using that printed directory as the context:

```bash
docker build --pull -t agent-fleet-runner:0.1.0-py314-v1 /printed/runner/directory
docker image inspect agent-fleet-runner:0.1.0-py314-v1
```

The operator's build may download the pinned Python base and hash-checked wheels
from the official Python package index. Fleet itself never builds or pulls an
image, installs dependencies, or falls back to host execution. Use a local Unix
Docker daemon; the adapter resolves the image to its immutable ID and inspects
each non-root, no-network, read-only, resource-limited command container.

The OCI base index includes Linux arm64/v8 and amd64. Registry membership is not
platform acceptance; consult the release ledger for actual executed platforms.
This v1 runner contains only Python and genuine pytest dependencies, not every
project's compiler or test tools. Prepare a separately reviewed image when a
project needs additional tools. Never bake project credentials into an image.

The final scratch copy removes inherited image environment metadata; Fleet sets
the execution restrictions, so this recipe alone is not a sandbox. Exact base and
wheel hashes make inputs reviewable, not necessarily bit-identical image layers
across builders or architectures, and do not guarantee absence of vulnerabilities.
Change the recipe revision when any base/dependency input changes; retain the old
local immutable image while evidence or paused runs still refer to it. Never
silently substitute a new image for an admitted project/run.
