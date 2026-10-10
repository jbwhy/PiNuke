# PiNuke

**Experimental 0.3.0** — Raspberry Pi USB control for the Behringer NU6000DSP,
with a browser editor, live relative meters, and idealized response previews.
Connect the amplifier to the Pi; open the page from another computer or phone.
Windows is not required in this run path.

PiNuke's protocol module is adapted from
[Ryan Mathewson's inuke-oscd](https://github.com/RyanMathewson/inuke-oscd).
See [ATTRIBUTION.md](ATTRIBUTION.md) and the retained [upstream MIT license](UPSTREAM_LICENSE).

## Use at your own risk

PiNuke is an independent community project. It is not affiliated with, endorsed
by, or supported by Behringer or Music Group. Product and company names are used
for identification.

PiNuke is experimental software provided **as is, without warranty**. Incorrect
settings, software errors, or unexpected device behavior can damage amplifiers,
speakers, or other equipment, and excessive sound levels can damage hearing.
Users are responsible for checking compatibility, configuring appropriate
hardware protection, and verifying every change. PiNuke's validation, meters,
and previews do not guarantee safe operation or replace hardware protection.

Confirm settings against the amplifier's actual state using its controls or
an independent trusted tool; do not rely on a single display alone.

**To the maximum extent permitted by applicable law, the authors, contributors,
and copyright holders accept no liability for equipment damage, personal
injury, or other loss arising from use of this software.** See the [MIT license](LICENSE)
and [editing safety notes](docs/SAFETY.md).

## Features

- Both channels: eight PEQ bands, high/low-pass crossovers, DSP output gain,
  two dynamic EQ bands, delay/phase, and peak limiter controls.
- Explicit Read → stage → Apply workflow. Fresh state checks, persistent
  before-change records, and group/full readback verification protect edits.
- Opt-in live meters serialized with Read and Apply over one USB session.
- Optional homepage meter card: appears only while the amplifier is actually
  available and disappears after sustained loss; availability is independent
  of meter freshness. Opens the editor in a same-origin full-page dialog.
- Responsive single-page editor with crossover, EQ, dynamic EQ, delay, and
  limiter previews. The π button returns to the embedding homepage.
- JSON export of queried DSP state, excluding onboard preset slots.

The editor is independent of the homepage card. There is no required music
player, existing homepage, or external UI service.

## Quick start on a Pi

Install Python 3.9+ and the system HID libraries, give a non-root account
targeted USB access, then install PiNuke in a virtual environment. See
[INSTALL.md](docs/INSTALL.md) for permission and private HTTPS examples.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/pinuke scan
.venv/bin/pinuke serve
```

The service binds to `127.0.0.1:8765` by default, with editing and meters off.
For a loopback smoke check use `http://127.0.0.1:8765/`. For normal browser use,
proxy it under `/pinuke/` on a private authenticated HTTPS site. Set
`--public-origin` to that site's exact origin. The server has no built-in login.

```sh
.venv/bin/pinuke serve --public-origin https://amp.example \
  --enable-meters --enable-edits --audit-dir /var/lib/pinuke/changes
```

`amp.example` is a placeholder; replace it with your private site's hostname.
The audit directory must be writable by the service account before enabling
editing. Pause playback before a deliberate settings change. Only one
controller should own the amplifier's USB connection at a time.

## What has been verified

Live checks used one NU6000DSP with firmware **V1.3**, USB **1397:1101**, on a
Pi 4 using a libusb-backed hidapi installation. Successful checks covered
both-channel Read/export, a reversible DSP gain Apply/restore, session
reopening, serialized Read/meter resumption, continuous meters across periodic
identity queries, and power-off/on card disappearance/reappearance.
Desktop, intermediate, and phone layouts were checked.

Other amplifier models/firmware, HID backends, and every individual control's
live write behavior have not been established. Offline tests use synthetic
devices and settings, not captured user configurations.

## Limits

- Meters are **relative and uncalibrated**, not established dBFS, measured
  output voltage, or calibrated limiter headroom. Field/channel correlation
  and native clip/limiter activity indicators still need independent evidence.
  No verified calibration file is distributed.
- Graphs are **idealized previews**, not measured amplifier/room response.
  Crossover families use an approximation; dynamic EQ is a steady-state preview.
- Mode, name, analog level knobs, reported gain/mute, and onboard presets are
  not edited. Editable gain is DSP output trim.
- Export is not a full restorable backup; import is not implemented.
- Apply is sequential, not atomic. On mismatch/timeout it stops without retry
  or automatic restoration; some groups may already have changed. Read again
  before continuing. See [SAFETY.md](docs/SAFETY.md).
- Bounded live tests support this experimental release, not indefinite reliability.

## Support and security reporting

This is an experimental community project. Maintenance, updates, bug fixes,
compatibility, technical support, response times, continued availability, and
vulnerability monitoring are not guaranteed. Publishing source or accepting
reports does not create a commitment to provide those services.

For vulnerability reports, use the private reporting procedure in
[SECURITY.md](SECURITY.md). See [runtime data and logging](docs/PRIVACY.md#runtime-data-and-logging)
for information handled by the service, exports, audits, and logs.

## Optional integration and development

See [HOMEPAGE.md](docs/HOMEPAGE.md) for a generic meter-card example,
[METERS.md](docs/METERS.md) for telemetry behavior, and
[DEVELOPMENT.md](docs/DEVELOPMENT.md) for offline tests.
Before posting a bug report, follow [PRIVACY.md](docs/PRIVACY.md): exports and
audit records contain device identity and settings. Do not upload them raw.

MIT licensed; upstream copyright and license notices are retained.
