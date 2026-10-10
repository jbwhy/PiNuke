# Live meters and availability

Meters require `--enable-meters` and an active viewer. The client requests
approximately 10 reports/second; normal meter heartbeats renew around every
5 seconds. A viewer lease expires after roughly 8 seconds without activity.
Read and Apply close/handoff the monitor session under the same exclusive USB
lock; monitoring can resume afterward.

Periodic identity queries independently confirm actual availability. After an
identity reply, the communication session is renewed with `/online`, followed
by the usual conditional meter heartbeat. This preserved continuous reports
in bounded NU6000DSP V1.3 checks. Initialization uses
`/online → /info → /online → /gain → /ampmode`; moving `/online` before `/info`
without retaining the post-info step did not pass the tested gain handshake.
These are communication reports, not DSP setters. Internal firmware causes
of the earlier dropouts are not established.

The homepage card polls actual availability about every 2 seconds and uses a
short grace period to avoid flicker. Missing meters do not hide a responsive
amp. Lost/expired identity hides the card; confirmed reconnect can show it
again. An open editor remains open so pending edits are not discarded.
Power-off delays depend on the installation; shortcut state or an elapsed
timer is never substituted for device availability.

## Units and evidence

Four finite nonnegative meter fields are displayed as relative A/B input/output
levels. Their physical field/channel correlation and scale need independent
verification. Values use `20 log10(amplitude / 1)` without calibration. This is
not established dBFS, output voltage, or limiter headroom. Peak markers hold
for 1.4 seconds; missing samples clear the display.

Native clip/limiter activity flags are not decoded or claimed. Graphs remain
idealized. The calibration loader is experimental: a verified, serial/firmware-
bound file is required, and mismatch disables it. No calibration file or
usable calibration numbers are distributed. Do not mark synthetic values as
verified. Calibration and native indicator verification remain future work.

## API distinction

- `/api/meters` and `/api/availability` renew viewer leases and may cause live
  USB work. The availability endpoint can discover the amp even with meters off.
- `/api/meter-state` and `/api/availability-state` read cached state only.
- `/api/state` and `/api/controls` read cached DSP state/control metadata.
- `/api/readback` and `/api/apply` are explicit POST transactions.

When constructing a strictly observational connector, use cache-only endpoints;
do not assume all GETs avoid device communication. API identity/export/audit data
is private. No analytics or external telemetry service is included.
