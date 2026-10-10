# Installation

These are examples for a Debian/Raspberry Pi OS host. Paths and hostnames are
generic; adapt them to your system. No script here installs or operates a device.

## Python and USB

```sh
sudo apt-get install python3-venv libhidapi-libusb0 libhidapi-hidraw0
python3 -m venv .venv
.venv/bin/python -m pip install .
lsusb -d 1397:1101
.venv/bin/pinuke scan
```

Enumeration does not open the amplifier and does not establish permission to
query it. The verified installation used **libusb**: it required read/write
access to `/dev/bus/usb/...`, not merely `/dev/hidraw*`. USB bus/device numbers
change after reconnecting. Run the controller as a non-root account.

For a dedicated account in a `pinuke` group, an administrator can install the
following as `/etc/udev/rules.d/70-pinuke.rules`:

```udev
SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="1397", ATTR{idProduct}=="1101", GROUP="pinuke", MODE="0660"
```

Create the group and grant only the intended service account membership, reload
udev rules, and reconnect the USB device. Confirm the resulting node's ownership
and mode. This grants access only to the matching VID/PID. Do not grant access
to every USB device. A hidraw backend needs a separately reviewed, device-specific
hidraw rule; it has not been verified here.

Close other USB controllers before running these progressively broader checks:

```sh
umask 077
.venv/bin/pinuke opencheck
.venv/bin/pinuke status
.venv/bin/pinuke read before.json
```

`opencheck` opens/closes without sending PiNuke reports. `status` checks the
communication handshake; `read` queries both channels and refuses to overwrite
its output. They do not send DSP setters, but `status` and `read` communicate
with the amplifier. `probe` queries identity only and is not a substitute for
the full status handshake. Stop at the first failure and diagnose permission,
backend, or session ownership before proceeding.

## Private browser access

Keep the Python server on loopback. An example Caddy route is in
`examples/Caddyfile`; provide a resolvable hostname, trusted certificate, and
your own private access/authentication policy. `--public-origin` must match the
browser's scheme/hostname/port, without a path:

```sh
.venv/bin/pinuke serve --public-origin https://amp.example --enable-meters
```

The proxy must strip `/pinuke` and redirect `/pinuke` to `/pinuke/`. The homepage
dialog must share the editor's origin. PiNuke emits SAMEORIGIN framing and
`frame-ancestors 'self'`; do not relax framing globally on an existing site.
Origin checking is a request safeguard, **not authentication**. Do not expose
the service directly to the public internet.

## Editing and service account

Create a private, persistent audit directory writable by the service account;
the example uses `/var/lib/pinuke/changes`. Records must survive upgrades.
Then opt in with `--enable-edits --audit-dir /var/lib/pinuke/changes`.

`examples/pinuke.service` assumes a virtual environment under `/opt/pinuke/.venv`,
a `pinuke` account/group, and the generic private HTTPS origin. Adjust these
before installing it. Ensure service storage is mounted and writable before
startup; on removable/SSD-backed storage add a mount requirement appropriate
to that host. Never run the example blindly over an existing service.

Start with read-only access. Read the amp, stage one deliberate reversible
change, review it, and Apply with playback paused. Other controls should be
verified cautiously on the actual hardware before relying on them.
