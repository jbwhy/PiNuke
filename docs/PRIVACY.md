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
