# Security policy

## Reporting a vulnerability

Use GitHub's **Security → Report a vulnerability** for this repository:
[private reporting](https://github.com/jbwhy/PiNuke/security/advisories/new).
This sends the report privately through GitHub rather than a public issue.
Do not post vulnerability details, exploit instructions, or sensitive device
records in public issues or pull requests.

Include the affected version or commit, expected and observed behavior, impact,
and a minimal synthetic reproduction if possible. Remove passwords, keys,
private hostnames, serial numbers, personal information, and real settings,
exports, audits, logs, or captures. Private reporting is not a reason to share
unnecessary sensitive data. Do not test on someone else's equipment or change
live amplifier settings without that owner's authorization.

If GitHub private reporting is unavailable, open a public issue requesting a
private reporting channel **without vulnerability details or sensitive data**.

## Status and expectations

PiNuke is experimental. There is no guaranteed security-supported version,
maintenance schedule, vulnerability monitoring, response time, fix, or continued
availability. A private reporting channel does not establish any such commitment.
The published verification scope and limits are described in the README.

## Deployment considerations

The server binds to loopback by default and has no built-in login or TLS.
For browser access, use a private authenticated HTTPS reverse proxy and restrict
access to trusted users. The operator is responsible for host, network, proxy,
dependency, and USB access configuration. Origin checks and readback validation
do not replace authentication or hardware protection.

The software can change real amplifier settings. Use the
[editing safety guidance](docs/SAFETY.md), [risk disclaimer](README.md#use-at-your-own-risk),
and [runtime data disclosure](docs/PRIVACY.md#runtime-data-and-logging).
This policy is reporting guidance, not a security certification.
