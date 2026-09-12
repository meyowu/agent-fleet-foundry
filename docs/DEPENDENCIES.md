# Dependency and runner policy

Supported Python range is3.12–3.14. Git>=2.45 is required for hardened Git process
flags. Full execution also depends on local POSIX/native filesystem operations and
a local Linux Docker daemon. Windows and remote filesystems are not advertised as
supported; cross-platform acceptance requires actual jobs, not just classifiers.

`pyproject.toml` declares bounded compatible runtime ranges; `uv.lock` is the
contributor/CI resolution and includes all hashes and platform markers. The build
backend is pinned to Hatchling1.32.0 and included in the dev lock so explicit setup
can prepare offline build tools. The dev lock also pins pip26.2.1 for the explicit
wheelhouse preparation tool and its real configuration-isolation regression;
pip is not an added runtime dependency. Runtime dependencies serve concrete boundaries:
Pydantic validates contracts, PydanticAI/OpenAI adapt the selected harness/provider,
Typer/Rich present the CLI, PyYAML parses configuration and platformdirs selects
local state. Vendor objects do not cross domain/port contracts.

Contributor setup is explicitly network-enabled; subsequent checks use frozen
resolution and ordinary tests deny sockets/provider requests. Fresh release tests
create separate environments and empty install caches without system packages,
install from a prepared no-index wheelhouse under runtime/build constraints, and
prove the imported module/CLI resides there. They validate each wheel hash against
the current lock, not merely against a supplied manifest. Both wheel and sdist
installation are required. The earlier `--no-deps --target` import check remains a
separate packaging check, never a fresh-install substitute.

Use `scripts/prepare_release_dependencies.py --destination <new-absolute-path>`
as an explicit network setup step. It exports the frozen hash-bearing requirements
and runs pinned pip26.2.1 against the official index in isolated mode, with
`PIP_CONFIG_FILE` set to the null device to suppress global/site configuration too.
The runner applies that same guard only in its build stage. The target
Python interpreter is explicit (default: the active environment); macOS/Linux and
Python-version-specific wheels are not interchangeable. It writes a manifest with
lock/requirements hashes and observed interpreter/platform. Failed setup retains
its exact directory; use a new destination, never erase a broad cache to retry.

Runner v1 pins the OCI base index and five universal Python test wheels. Its
packaged build context is canonical; the source test Dockerfile is a byte-identical
compatibility copy. Updates must revise runner policy/version and test both actual
platforms. A tag is a human label, not immutable evidence; Fleet binds the local
image ID. Fixed hashes establish input identity, not vulnerability absence,
hardware isolation or identical images across builders. No runner registry is
published by this work.

## Updating dependencies

1. Review the direct/transitive purpose, license metadata, release notes and
   current security advisories from primary sources. Retain relevant findings.
2. Update the smallest justified range/pin; regenerate and review `uv.lock`.
   Do not execute arbitrary repository install scripts during Fleet profiling.
3. Rebuild a fresh wheelhouse for each tested interpreter/platform; never silently
   resolve around a frozen-lock mismatch or reuse unreviewed artifact bytes.
4. Run formatting/lint/types/schema/default/security/fresh-install checks; repeat
   real Docker inspection and both role command evidence when runner/tooling changes.
5. Record exact versions, hashes, result/failure evidence and supported-platform
   limits. A passing test is not an independent dependency vulnerability audit.

No automated CVE advisory scan or signed supply-chain attestation is claimed by
the initial release evidence. This project uses owner-selected Apache-2.0;
dependency license obligations remain separate. See [LICENSE](../LICENSE) and
the [release procedure](RELEASE.md).
