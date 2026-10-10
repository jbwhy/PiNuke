# Public contributions and privacy

Public source and examples must remain generic. Use a clean source allowlist,
not a copy of a private working tree or its Git history. Preserve upstream
attribution; exclude personal/business identifiers, private hostnames/IPs and
paths, credentials, actual serials, settings captures, logs, audits, screenshots,
and internal notes. Examples use reserved domains and synthetic fixtures.

Local Read/export and audit records intentionally include device identity and
DSP settings needed for safe editing. They are **not anonymized bug reports**.
Calibration files include device identity too. Do not attach these files raw to
issues. Describe the model/firmware and symptom; redact identifiers, hostname,
path, settings and timestamps from a minimal excerpt if needed.

`.gitignore` excludes typical runtime records and build artifacts, but it cannot
protect files already committed. Before a public push, inspect staged files and
history. `python3 tools/check_public_tree.py .` catches forbidden paths, live JSON
files and common identifier/credential patterns; it supplements human review.
It does not prove every possible secret has been found.

Do not add screenshots until their device details, browser chrome, hostnames,
personal media, and surrounding UI have been checked. This release includes
source-generated examples rather than private deployment screenshots.

## Runtime data and logging

PiNuke reads amplifier USB identity (including serial number and firmware),
DSP settings, and live meter/availability data. Read snapshots and monitoring
state are held in the server's memory. Device information and settings are sent
between the Pi service and the browser through the site's API; Apply sends the
requested setting changes back to the service. Anyone able to access those
endpoints may see device data, which is another reason to restrict access.

On request, browser or CLI exports save identity and DSP state to a file.
When editing is enabled, persistent local audit files record the before-state,
requested changes, timestamps, and verification/error outcome. Calibration files
also carry device identity. These records support editing checks and are not
anonymized. The operator chooses storage locations, access, retention, and
deletion; PiNuke does not automatically rotate or delete audit records.

The built-in HTTP server prints client address, request line, and response status
to standard output. A service manager may retain that output, and a reverse proxy
may keep its own logs. The visible client address may be the proxy's address.
Requests and errors may reveal paths or device context. Logging retention and
access depend on the operator's host/proxy configuration.

The PiNuke application has no built-in analytics or automatic device-data upload
to its maintainers. Normal runtime traffic is browser-to-host and host-to-amplifier.
Dependency installation, GitHub, and any external hosting/authentication services
have separate data practices. The server has no built-in login; authentication
and HTTPS are provided by the operator's chosen proxy.

Keep these files and logs private. For a security report, use
[SECURITY.md](../SECURITY.md) and provide only the minimum sanitized information.
