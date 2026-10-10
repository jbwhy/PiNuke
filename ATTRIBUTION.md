# Attribution

PiNuke builds on **Ryan Mathewson's inuke-oscd**, an open client and USB/OSC
protocol implementation for Behringer iNuke DSP amplifiers:

- Repository: https://github.com/RyanMathewson/inuke-oscd
- Adaptation baseline: `21cacc5d77c29e0d9ba5f261c6baa8d34cf169ac`
- License: MIT, copyright © 2026 Ryan Mathewson; retained in `UPSTREAM_LICENSE`.

`pinuke/_inuke_protocol.py` is adapted from that source. The original typed
requests, framing and conservative send pacing remain the protocol foundation.
PiNuke adds device selection/readback, guarded editing and audit records,
serialized viewer-leased telemetry, device availability, a web service and UI,
idealized graphs, and optional homepage integration.

References to `docs/PROTOCOL_NOTES.md` inside the adapted module refer to the
upstream repository's protocol notes; that upstream document is not bundled here.
Original protocol observations must not be mistaken for newly calibrated
PiNuke measurements or a specification for every amplifier model.

PiNuke is an independent derivative project and does not imply upstream or
manufacturer endorsement. Retain both license files when redistributing it.
