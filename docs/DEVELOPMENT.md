# Development

Python 3.9+; Node.js 20+ for the small JavaScript checks. Install locally in a
virtual environment, then run:

```sh
python3 -m unittest discover -s tests -v
node tests/test_graphs.mjs
node tests/test_presence.mjs
python3 tools/check_public_tree.py .
```

Tests use fake USB transports, synthetic settings/calibration, temporary audit
directories, and loopback HTTP. They do not open an amplifier. Local HTTP tests
require permission to bind loopback sockets. Do not turn test success into a
claim that a different model's controls or meter calibration are established.

The public source derives from the verified 0.3.0 implementation. Public-copy
changes generalize examples, CLI help and comments, replace private documentation,
and omit an installation-specific HTML patcher and its two tests. The scoped
layout check is retained without that patcher. DSP setters, validation, USB
transport, session sequencing, telemetry and audit logic remain unchanged.

Build with `python3 -m pip wheel --no-deps .` or a PEP 517 frontend. Review the
source tree, package members, licenses and metadata before publication. Avoid
embedding the absolute path of the build workstation in artifacts.
