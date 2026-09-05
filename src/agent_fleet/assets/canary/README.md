# Public learning canary

This tiny Python project deliberately fails one of five pytest cases: division by
zero must raise `ValueError("division by zero is not allowed")`. It contains no
credentials, private acceptance fixtures or setup hooks. It is an educational
example, not application code to import into Fleet.

Copy this directory into a **new** destination, initialize Git there and commit
the starting files using your own Git identity. Use the installed Fleet guide and
runner v1 to initialize the project with `--runtime fake --sandbox docker` and an
explicit local image. `fleet run "Fix the canary behavior" --project .` uses the
deterministic fake model but real Docker command execution. Inspect every exact
permission request, approve it explicitly, resume, inspect the evidence/patch and
apply only after review. The source stays broken until explicit code-patch apply.

This demonstrates isolated command evidence without a provider key. It does not
demonstrate general model reasoning or an actual model-provider call. FakeSandbox
does not execute tests and cannot satisfy public initialization's canary gate.
